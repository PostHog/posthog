from posthog.test.base import BaseTest

from posthog.hogql.query import execute_hogql_query

# One expression per newly allowlisted IP function, so a typo'd mapping entry
# (wrong name, wrong arity) fails here instead of at user query time.
IP_FUNCTION_CASES: list[tuple[str, object]] = [
    ("IPv4NumToString(IPv4StringToNum('66.249.84.5'))", "66.249.84.5"),
    ("IPv4StringToNumOrDefault('nope')", 0),
    ("isNull(IPv4StringToNumOrNull('nope'))", 1),
    ("IPv6NumToString(IPv6StringToNum('2001:db8::1'))", "2001:db8::1"),
    ("IPv6NumToString(IPv6StringToNumOrDefault('nope'))", "::"),
    ("isNull(IPv6StringToNumOrNull('nope'))", 1),
    ("IPv6NumToString(IPv4ToIPv6(IPv4StringToNum('1.2.3.4')))", "::ffff:1.2.3.4"),
    ("toString(toIPv4('1.2.3.4'))", "1.2.3.4"),
    ("toString(toIPv4OrDefault('nope'))", "0.0.0.0"),
    ("isNull(toIPv4OrNull('nope'))", 1),
    ("toString(toIPv4OrZero('nope'))", "0.0.0.0"),
    ("toString(toIPv6('::1'))", "::1"),
    ("toString(toIPv6OrDefault('nope'))", "::"),
    ("isNull(toIPv6OrNull('nope'))", 1),
    ("toString(toIPv6OrZero('nope'))", "::"),
    ("isIPv4String('1.2.3.4')", 1),
    ("isIPv6String('::1')", 1),
    ("isIPAddressInRange('66.249.84.5', '66.249.80.0/20')", 1),
    ("toString(tupleElement(IPv4CIDRToRange(toIPv4('192.168.5.2'), 16), 1))", "192.168.0.0"),
    ("toString(tupleElement(IPv6CIDRToRange(toIPv6('2001:db8::8a2e:370:7334'), 32), 1))", "2001:db8::"),
    ("toString(cutIPv6(toIPv6('2001:db8::8a2e:370:7334'), 2, 0))", "2001:db8::8a2e:370:0"),
]


class TestIPFunctions(BaseTest):
    def test_ip_functions_execute(self):
        select = ", ".join(expression for expression, _ in IP_FUNCTION_CASES)
        response = execute_hogql_query(f"SELECT {select}", self.team)

        assert len(response.results) == 1
        for (expression, expected), actual in zip(IP_FUNCTION_CASES, response.results[0]):
            assert actual == expected, f"{expression}: expected {expected!r}, got {actual!r}"
