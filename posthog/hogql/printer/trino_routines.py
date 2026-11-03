"""Trino inline SQL routines (`WITH FUNCTION`) for ClickHouse functions that Trino lacks.

A routine block must start the whole statement, so the printer only records which routines a query
uses. Each caller puts `trino_routines_prefix(...)` in front of the final statement it runs.

Every routine body is a single RETURN expression. A BEGIN ... END body holds `;`, which the
single-statement guards on the direct-query paths reject.
"""

from collections.abc import Collection

CITY_HASH_64_ROUTINE = "hogql_city_hash_64"
INT_HASH_64_ROUTINE = "hogql_city_hash_64_int"

_MASK_64 = (1 << 64) - 1


def _bigint(value: int) -> str:
    # UInt64 values travel as their two's complement bit pattern in BIGINT.
    value &= _MASK_64
    return f"BIGINT '{value - (1 << 64) if value >= 1 << 63 else value}'"


_K0 = _bigint(0xC3A5C85C97CB3127)
_K1 = _bigint(0xB492B66FBE98F273)
_K2 = _bigint(0x9AE16A3B2F90404F)
_K3 = _bigint(0xC949D7C7509E6557)
_K_MUL = _bigint(0x9DDFEA08EB382D69)
_TWO_64 = "DECIMAL '18446744073709551616'"


def _wrap(decimal_expr: str) -> str:
    # Trino BIGINT arithmetic raises on overflow, so add and multiply run in DECIMAL(38, 0)
    # and fold back to the 64-bit two's complement pattern that C++ unsigned arithmetic keeps.
    return (
        f"CAST(mod(mod({decimal_expr}, {_TWO_64}) + DECIMAL '27670116110564327424', {_TWO_64})"
        " - DECIMAL '9223372036854775808' AS BIGINT)"
    )


def _dec(name: str) -> str:
    return f"CAST({name} AS DECIMAL(38, 0))"


_PAIR = "ROW(bigint, bigint)"
_STATE = "ROW(bigint, bigint, bigint, bigint, bigint, bigint, bigint)"

# CityHash v1.0.2, the version ClickHouse's cityHash64 uses. Dependencies come first.
_CITY_HASH_64_FUNCTIONS: tuple[str, ...] = (
    f"FUNCTION hogql_ch_add(a bigint, b bigint) RETURNS bigint RETURN {_wrap(_dec('a') + ' + ' + _dec('b'))}",
    f"FUNCTION hogql_ch_sub(a bigint, b bigint) RETURNS bigint RETURN {_wrap(_dec('a') + ' - ' + _dec('b'))}",
    f"FUNCTION hogql_ch_mul(a bigint, b bigint) RETURNS bigint RETURN {_wrap(_dec('a') + ' * ' + _dec('b'))}",
    "FUNCTION hogql_ch_rot(v bigint, s integer) RETURNS bigint"
    " RETURN IF(s = 0, v, bitwise_or(bitwise_right_shift(v, s), bitwise_left_shift(v, 64 - s)))",
    "FUNCTION hogql_ch_sm(v bigint) RETURNS bigint RETURN bitwise_xor(v, bitwise_right_shift(v, 47))",
    "FUNCTION hogql_ch_f64(s varbinary, p bigint) RETURNS bigint"
    " RETURN from_big_endian_64(reverse(substr(s, p + 1, 8)))",
    "FUNCTION hogql_ch_f32(s varbinary, p bigint) RETURNS bigint"
    " RETURN bitwise_and(CAST(from_big_endian_32(reverse(substr(s, p + 1, 4))) AS bigint), 4294967295)",
    "FUNCTION hogql_ch_byte(s varbinary, p bigint) RETURNS bigint"
    " RETURN CAST(from_big_endian_32(X'000000' || substr(s, p + 1, 1)) AS bigint)",
    # HashLen16
    "FUNCTION hogql_ch_h16b(v bigint, a bigint) RETURNS bigint"
    f" RETURN hogql_ch_mul(hogql_ch_sm(hogql_ch_mul(bitwise_xor(v, a), {_K_MUL})), {_K_MUL})",
    "FUNCTION hogql_ch_h16(u bigint, v bigint) RETURNS bigint"
    f" RETURN hogql_ch_h16b(v, hogql_ch_sm(hogql_ch_mul(bitwise_xor(u, v), {_K_MUL})))",
    # HashLen0to16
    "FUNCTION hogql_ch_9_16(s varbinary, n bigint, b bigint) RETURNS bigint"
    " RETURN bitwise_xor(hogql_ch_h16(hogql_ch_f64(s, 0), hogql_ch_rot(hogql_ch_add(b, n), CAST(n AS integer))), b)",
    "FUNCTION hogql_ch_1_3(y bigint, z bigint) RETURNS bigint"
    f" RETURN hogql_ch_mul(hogql_ch_sm(bitwise_xor(hogql_ch_mul(y, {_K2}), hogql_ch_mul(z, {_K3}))), {_K2})",
    "FUNCTION hogql_ch_0_16(s varbinary, n bigint) RETURNS bigint RETURN CASE"
    " WHEN n > 8 THEN hogql_ch_9_16(s, n, hogql_ch_f64(s, n - 8))"
    " WHEN n >= 4 THEN hogql_ch_h16(hogql_ch_add(n, bitwise_left_shift(hogql_ch_f32(s, 0), 3)), hogql_ch_f32(s, n - 4))"
    " WHEN n > 0 THEN hogql_ch_1_3("
    "hogql_ch_add(hogql_ch_byte(s, 0), bitwise_left_shift(hogql_ch_byte(s, n / 2), 8)),"
    " hogql_ch_add(n, bitwise_left_shift(hogql_ch_byte(s, n - 1), 2)))"
    f" ELSE {_K2} END",
    # HashLen17to32
    "FUNCTION hogql_ch_17_32b(n bigint, a bigint, b bigint, c bigint, d bigint) RETURNS bigint RETURN hogql_ch_h16("
    "hogql_ch_add(hogql_ch_add(hogql_ch_rot(hogql_ch_sub(a, b), 43), hogql_ch_rot(c, 30)), d),"
    f" hogql_ch_add(hogql_ch_sub(hogql_ch_add(a, hogql_ch_rot(bitwise_xor(b, {_K3}), 20)), c), n))",
    "FUNCTION hogql_ch_17_32(s varbinary, n bigint) RETURNS bigint RETURN hogql_ch_17_32b(n,"
    f" hogql_ch_mul(hogql_ch_f64(s, 0), {_K1}), hogql_ch_f64(s, 8),"
    f" hogql_ch_mul(hogql_ch_f64(s, n - 8), {_K2}), hogql_ch_mul(hogql_ch_f64(s, n - 16), {_K0}))",
    # HashLen33to64: both halves share one shape, returned as (first, second).
    f"FUNCTION hogql_ch_half3(b bigint, c bigint, a bigint, z bigint) RETURNS {_PAIR}"
    " RETURN ROW(hogql_ch_add(a, z), hogql_ch_add(hogql_ch_add(b, hogql_ch_rot(a, 31)), c))",
    f"FUNCTION hogql_ch_half2(b bigint, c bigint, a bigint, q bigint, z bigint) RETURNS {_PAIR}"
    " RETURN hogql_ch_half3(b, hogql_ch_add(c, hogql_ch_rot(a, 7)), hogql_ch_add(a, q), z)",
    f"FUNCTION hogql_ch_half(a bigint, z bigint, p bigint, q bigint) RETURNS {_PAIR}"
    " RETURN hogql_ch_half2(hogql_ch_rot(hogql_ch_add(a, z), 52), hogql_ch_rot(a, 37), hogql_ch_add(a, p), q, z)",
    "FUNCTION hogql_ch_33_64c(vs bigint, r bigint) RETURNS bigint"
    f" RETURN hogql_ch_mul(hogql_ch_sm(hogql_ch_add(hogql_ch_mul(r, {_K0}), vs)), {_K2})",
    f"FUNCTION hogql_ch_33_64b(v {_PAIR}, w {_PAIR}) RETURNS bigint RETURN hogql_ch_33_64c(v[2], hogql_ch_sm("
    f"hogql_ch_add(hogql_ch_mul(hogql_ch_add(v[1], w[2]), {_K2}), hogql_ch_mul(hogql_ch_add(w[1], v[2]), {_K0}))))",
    "FUNCTION hogql_ch_33_64(s varbinary, n bigint) RETURNS bigint RETURN hogql_ch_33_64b("
    f"hogql_ch_half(hogql_ch_add(hogql_ch_f64(s, 0), hogql_ch_mul(hogql_ch_add(n, hogql_ch_f64(s, n - 16)), {_K0})),"
    " hogql_ch_f64(s, 24), hogql_ch_f64(s, 8), hogql_ch_f64(s, 16)),"
    " hogql_ch_half(hogql_ch_add(hogql_ch_f64(s, 16), hogql_ch_f64(s, n - 32)),"
    " hogql_ch_f64(s, n - 8), hogql_ch_f64(s, n - 24), hogql_ch_f64(s, n - 16)))",
    # WeakHashLen32WithSeeds(s + p, a, b)
    f"FUNCTION hogql_ch_weak3(a bigint, b bigint, c bigint, z bigint) RETURNS {_PAIR}"
    " RETURN ROW(hogql_ch_add(a, z), hogql_ch_add(hogql_ch_add(b, hogql_ch_rot(a, 44)), c))",
    f"FUNCTION hogql_ch_weak2(s varbinary, p bigint, a bigint, b bigint) RETURNS {_PAIR} RETURN hogql_ch_weak3("
    "hogql_ch_add(hogql_ch_add(a, hogql_ch_f64(s, p + 8)), hogql_ch_f64(s, p + 16)),"
    " hogql_ch_rot(hogql_ch_add(hogql_ch_add(b, a), hogql_ch_f64(s, p + 24)), 21), a, hogql_ch_f64(s, p + 24))",
    f"FUNCTION hogql_ch_weak(s varbinary, p bigint, a bigint, b bigint) RETURNS {_PAIR}"
    " RETURN hogql_ch_weak2(s, p, hogql_ch_add(a, hogql_ch_f64(s, p)), b)",
    # One 64-byte step of the long-input loop. State is (x, y, z, v.first, v.second, w.first, w.second).
    f"FUNCTION hogql_ch_step3(x bigint, y bigint, z bigint, v {_PAIR}, w {_PAIR}) RETURNS {_STATE}"
    " RETURN ROW(z, y, x, v[1], v[2], w[1], w[2])",
    "FUNCTION hogql_ch_step2(s varbinary, p bigint, x bigint, y bigint, z bigint, vs bigint, wf bigint, ws bigint)"
    f" RETURNS {_STATE} RETURN hogql_ch_step3(x, y, z,"
    f" hogql_ch_weak(s, p, hogql_ch_mul(vs, {_K1}), hogql_ch_add(x, wf)),"
    " hogql_ch_weak(s, p + 32, hogql_ch_add(z, ws), y))",
    f"FUNCTION hogql_ch_step(t {_STATE}, s varbinary, p bigint) RETURNS {_STATE} RETURN hogql_ch_step2(s, p,"
    " bitwise_xor(hogql_ch_mul(hogql_ch_rot(hogql_ch_add(hogql_ch_add(hogql_ch_add(t[1], t[2]), t[4]),"
    f" hogql_ch_f64(s, p + 16)), 37), {_K1}), t[7]),"
    f" bitwise_xor(hogql_ch_mul(hogql_ch_rot(hogql_ch_add(hogql_ch_add(t[2], t[5]), hogql_ch_f64(s, p + 48)), 42),"
    f" {_K1}), t[4]),"
    " hogql_ch_rot(bitwise_xor(t[3], t[6]), 33), t[5], t[6], t[7])",
    f"FUNCTION hogql_ch_finish(t {_STATE}) RETURNS bigint RETURN hogql_ch_h16("
    f"hogql_ch_add(hogql_ch_add(hogql_ch_h16(t[4], t[6]), hogql_ch_mul(hogql_ch_sm(t[2]), {_K1})), t[3]),"
    " hogql_ch_add(hogql_ch_h16(t[5], t[7]), t[1]))",
    # Trino has no loop in a single-expression routine, so the 64-byte loop is a reduce over the block offsets.
    f"FUNCTION hogql_ch_over64c(s varbinary, n bigint, x bigint, y bigint, z bigint, v {_PAIR}, w {_PAIR})"
    " RETURNS bigint RETURN hogql_ch_finish(reduce(sequence(0, (n - 1) / 64 - 1),"
    f" ROW(hogql_ch_mul(hogql_ch_rot(hogql_ch_add(z, x), 39), {_K1}), hogql_ch_mul(hogql_ch_rot(y, 33), {_K1}),"
    " z, v[1], v[2], w[1], w[2]),"
    " (t, i) -> hogql_ch_step(t, s, i * 64), t -> t))",
    f"FUNCTION hogql_ch_over64b(s varbinary, n bigint, x bigint, y bigint, z bigint, v {_PAIR}, w {_PAIR})"
    f" RETURNS bigint RETURN hogql_ch_over64c(s, n, x, y, hogql_ch_add(z, hogql_ch_mul(hogql_ch_sm(v[2]), {_K1})), v, w)",
    "FUNCTION hogql_ch_over64a(s varbinary, n bigint, x bigint, y bigint, z bigint) RETURNS bigint"
    " RETURN hogql_ch_over64b(s, n, x, y, z, hogql_ch_weak(s, n - 64, n, y),"
    f" hogql_ch_weak(s, n - 32, hogql_ch_mul(n, {_K1}), {_K0}))",
    "FUNCTION hogql_ch_over64(s varbinary, n bigint) RETURNS bigint RETURN hogql_ch_over64a(s, n, hogql_ch_f64(s, 0),"
    f" bitwise_xor(hogql_ch_f64(s, n - 16), {_K1}), bitwise_xor(hogql_ch_f64(s, n - 56), {_K0}))",
    "FUNCTION hogql_ch_unsigned(h bigint) RETURNS DECIMAL(20, 0)"
    f" RETURN CAST(CAST(h AS DECIMAL(38, 0)) + IF(h < 0, {_TWO_64}, DECIMAL '0') AS DECIMAL(20, 0))",
    f"FUNCTION {CITY_HASH_64_ROUTINE}(s varbinary) RETURNS DECIMAL(20, 0) RETURNS NULL ON NULL INPUT"
    " RETURN hogql_ch_unsigned(CASE"
    " WHEN length(s) <= 16 THEN hogql_ch_0_16(s, length(s))"
    " WHEN length(s) <= 32 THEN hogql_ch_17_32(s, length(s))"
    " WHEN length(s) <= 64 THEN hogql_ch_33_64(s, length(s))"
    " ELSE hogql_ch_over64(s, length(s)) END)",
    # ClickHouse hashes an integer as intHash64 of its value widened to UInt64, xor a fixed salt.
    # A negative value widens differently per source width, which HogQL types do not carry, so it fails.
    "FUNCTION hogql_ch_int_mix(x bigint) RETURNS bigint RETURN bitwise_xor(x, bitwise_right_shift(x, 33))",
    f"FUNCTION {INT_HASH_64_ROUTINE}(v DECIMAL(38, 0)) RETURNS DECIMAL(20, 0) RETURNS NULL ON NULL INPUT"
    " RETURN IF(v < 0 OR v > DECIMAL '18446744073709551615',"
    " fail('cityHash64 on Trino supports only integers from 0 to 18446744073709551615'),"
    " hogql_ch_unsigned(hogql_ch_int_mix(hogql_ch_mul(hogql_ch_int_mix(hogql_ch_mul(hogql_ch_int_mix("
    f"bitwise_xor({_wrap('v')}, {_bigint(0x4CF2D2BAAE6DA887)})), {_bigint(0xFF51AFD7ED558CCD)})),"
    f" {_bigint(0xC4CEB9FE1A85EC53)}))))",
)

_ROUTINE_FUNCTIONS: dict[str, tuple[str, ...]] = {
    CITY_HASH_64_ROUTINE: _CITY_HASH_64_FUNCTIONS,
    INT_HASH_64_ROUTINE: _CITY_HASH_64_FUNCTIONS,
}


def trino_routines_prefix(routines: Collection[str]) -> str:
    """Return the `WITH FUNCTION ...` block for the given routines, or "" when there are none."""
    functions: list[str] = []
    for name in sorted(routines):
        for function in _ROUTINE_FUNCTIONS[name]:
            if function not in functions:
                functions.append(function)
    if not functions:
        return ""
    return "WITH\n" + ",\n".join(functions) + "\n"
