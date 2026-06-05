# Golden output for the HogQL property-handling characterization corpus (logical cases).
# Harness-owned (NOT a .ambr snapshot) — regenerate with `UPDATE_PROPERTY_GOLDEN=1 hogli test <this file>`.
# Locks the MASTER logical-access rendering across dialects; team-id literals normalized to <TEAM>.
# Text churn here from a result-equivalent rewrite is reviewed per-PR, not auto-accepted (doc §8.7/§12.6).


#### simple_read  —  single top-level property read
## hogql-source: SELECT properties.foo FROM events
-- hogql
SELECT properties.foo FROM events LIMIT 50000
-- clickhouse
SELECT replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^"|"$', '') AS foo FROM events WHERE equals(events.team_id, <TEAM>) LIMIT 50000
-- postgres
SELECT (events.properties) ->> 'foo' AS "properties.foo" FROM events LIMIT 50000
-- duckdb
SELECT (events.properties) ->> 'foo' AS "properties.foo" FROM events LIMIT 50000

#### bracket_access  —  bracket index syntax, same as dot
## hogql-source: SELECT properties['foo'] FROM events
-- hogql
SELECT properties.foo FROM events LIMIT 50000
-- clickhouse
SELECT replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^"|"$', '') FROM events WHERE equals(events.team_id, <TEAM>) LIMIT 50000
-- postgres
SELECT (events.properties) ->> 'foo' AS "properties.foo" FROM events LIMIT 50000
-- duckdb
SELECT (events.properties) ->> 'foo' AS "properties.foo" FROM events LIMIT 50000

#### special_char_key  —  property key needing identifier quoting (synthetic, never materialized — quoting is a logical concern)
## hogql-source: SELECT properties.`weird key` FROM events
-- hogql
SELECT properties.`weird key` FROM events LIMIT 50000
-- clickhouse
SELECT replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^"|"$', '') AS `weird key` FROM events WHERE equals(events.team_id, <TEAM>) LIMIT 50000
-- postgres
SELECT (events.properties) ->> 'weird key' AS "properties.weird key" FROM events LIMIT 50000
-- duckdb
SELECT (events.properties) ->> 'weird key' AS "properties.weird key" FROM events LIMIT 50000

#### deep_chain  —  nested object chain a.b.c
## hogql-source: SELECT properties.a.b.c FROM events
-- hogql
SELECT properties.a.b.c FROM events LIMIT 50000
-- clickhouse
SELECT replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s, %(hogql_val_1)s, %(hogql_val_2)s), ''), 'null'), '^"|"$', '') AS a__b__c FROM events WHERE equals(events.team_id, <TEAM>) LIMIT 50000
-- postgres
SELECT (((events.properties) -> 'a') -> 'b') ->> 'c' AS "properties.a.b.c" FROM events LIMIT 50000
-- duckdb
SELECT (((events.properties) -> 'a') -> 'b') ->> 'c' AS "properties.a.b.c" FROM events LIMIT 50000

#### array_index  —  integer chain element is an array index, passed through untyped
## hogql-source: SELECT properties.arr.1 FROM events
-- hogql
SELECT properties.arr.1 FROM events LIMIT 50000
-- clickhouse
SELECT replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s, %(hogql_val_1)s), ''), 'null'), '^"|"$', '') FROM events WHERE equals(events.team_id, <TEAM>) LIMIT 50000
-- postgres
SELECT ((events.properties) -> 'arr') ->> 1 AS "properties.arr.1" FROM events LIMIT 50000
-- duckdb
SELECT ((events.properties) -> 'arr') ->> 1 AS "properties.arr.1" FROM events LIMIT 50000

#### deep_mixed  —  mixed object/array deep chain
## hogql-source: SELECT properties.obj.items.1.id FROM events
-- hogql
SELECT properties.obj.items.1.id FROM events LIMIT 50000
-- clickhouse
SELECT replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s, %(hogql_val_1)s, %(hogql_val_2)s, %(hogql_val_3)s), ''), 'null'), '^"|"$', '') FROM events WHERE equals(events.team_id, <TEAM>) LIMIT 50000
-- postgres
SELECT ((((events.properties) -> 'obj') -> 'items') -> 1) ->> 'id' AS "properties.obj.items.1.id" FROM events LIMIT 50000
-- duckdb
SELECT ((((events.properties) -> 'obj') -> 'items') -> 1) ->> 'id' AS "properties.obj.items.1.id" FROM events LIMIT 50000

#### is_null  —  IS NULL — must stay a key-existence/JSON read, never a non-nullable mat column
## hogql-source: SELECT properties.foo FROM events WHERE properties.foo IS NULL
-- hogql
SELECT properties.foo FROM events WHERE equals(properties.foo, NULL) LIMIT 50000
-- clickhouse
SELECT replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^"|"$', '') AS foo FROM events WHERE and(equals(events.team_id, <TEAM>), isNull(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_1)s), ''), 'null'), '^"|"$', ''))) LIMIT 50000
-- postgres
SELECT (events.properties) ->> 'foo' AS "properties.foo" FROM events WHERE ((events.properties) ->> 'foo' IS NULL) LIMIT 50000
-- duckdb
SELECT (events.properties) ->> 'foo' AS "properties.foo" FROM events WHERE ((events.properties) ->> 'foo' IS NULL) LIMIT 50000

#### is_not_null  —  IS NOT NULL counterpart
## hogql-source: SELECT properties.foo FROM events WHERE properties.foo IS NOT NULL
-- hogql
SELECT properties.foo FROM events WHERE notEquals(properties.foo, NULL) LIMIT 50000
-- clickhouse
SELECT replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^"|"$', '') AS foo FROM events WHERE and(equals(events.team_id, <TEAM>), isNotNull(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_1)s), ''), 'null'), '^"|"$', ''))) LIMIT 50000
-- postgres
SELECT (events.properties) ->> 'foo' AS "properties.foo" FROM events WHERE ((events.properties) ->> 'foo' IS NOT NULL) LIMIT 50000
-- duckdb
SELECT (events.properties) ->> 'foo' AS "properties.foo" FROM events WHERE ((events.properties) ->> 'foo' IS NOT NULL) LIMIT 50000

#### eq_null  —  = NULL (is-not-set) — same key-existence requirement as IS NULL
## hogql-source: SELECT properties.foo FROM events WHERE properties.foo = NULL
-- hogql
SELECT properties.foo FROM events WHERE equals(properties.foo, NULL) LIMIT 50000
-- clickhouse
SELECT replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^"|"$', '') AS foo FROM events WHERE and(equals(events.team_id, <TEAM>), isNull(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_1)s), ''), 'null'), '^"|"$', ''))) LIMIT 50000
-- postgres
SELECT (events.properties) ->> 'foo' AS "properties.foo" FROM events WHERE ((events.properties) ->> 'foo' = NULL) LIMIT 50000
-- duckdb
SELECT (events.properties) ->> 'foo' AS "properties.foo" FROM events WHERE ((events.properties) ->> 'foo' = NULL) LIMIT 50000

#### compare_eq  —  equality against a string constant
## hogql-source: SELECT properties.foo FROM events WHERE properties.bar = 'x'
-- hogql
SELECT properties.foo FROM events WHERE equals(properties.bar, 'x') LIMIT 50000
-- clickhouse
SELECT replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^"|"$', '') AS foo FROM events WHERE and(equals(events.team_id, <TEAM>), ifNull(equals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_1)s), ''), 'null'), '^"|"$', ''), %(hogql_val_2)s), 0)) LIMIT 50000
-- postgres
SELECT (events.properties) ->> 'foo' AS "properties.foo" FROM events WHERE ((events.properties) ->> 'bar' = %(hogql_val_0)s) LIMIT 50000
-- duckdb
SELECT (events.properties) ->> 'foo' AS "properties.foo" FROM events WHERE ((events.properties) ->> 'bar' = %(hogql_val_0)s) LIMIT 50000

#### compare_neq  —  inequality
## hogql-source: SELECT properties.foo FROM events WHERE properties.bar != 'x'
-- hogql
SELECT properties.foo FROM events WHERE notEquals(properties.bar, 'x') LIMIT 50000
-- clickhouse
SELECT replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^"|"$', '') AS foo FROM events WHERE and(equals(events.team_id, <TEAM>), ifNull(notEquals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_1)s), ''), 'null'), '^"|"$', ''), %(hogql_val_2)s), 1)) LIMIT 50000
-- postgres
SELECT (events.properties) ->> 'foo' AS "properties.foo" FROM events WHERE ((events.properties) ->> 'bar' != %(hogql_val_0)s) LIMIT 50000
-- duckdb
SELECT (events.properties) ->> 'foo' AS "properties.foo" FROM events WHERE ((events.properties) ->> 'bar' != %(hogql_val_0)s) LIMIT 50000

#### compare_in  —  IN list
## hogql-source: SELECT properties.foo FROM events WHERE properties.bar IN ('a', 'b')
-- hogql
SELECT properties.foo FROM events WHERE in(properties.bar, tuple('a', 'b')) LIMIT 50000
-- clickhouse
SELECT replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^"|"$', '') AS foo FROM events WHERE and(equals(events.team_id, <TEAM>), in(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_1)s), ''), 'null'), '^"|"$', ''), tuple(%(hogql_val_2)s, %(hogql_val_3)s))) LIMIT 50000
-- postgres
SELECT (events.properties) ->> 'foo' AS "properties.foo" FROM events WHERE ((events.properties) ->> 'bar' IN (%(hogql_val_0)s, %(hogql_val_1)s)) LIMIT 50000
-- duckdb
SELECT (events.properties) ->> 'foo' AS "properties.foo" FROM events WHERE ((events.properties) ->> 'bar' IN (%(hogql_val_0)s, %(hogql_val_1)s)) LIMIT 50000

#### compare_not_in  —  NOT IN list
## hogql-source: SELECT properties.foo FROM events WHERE properties.bar NOT IN ('a', 'b')
-- hogql
SELECT properties.foo FROM events WHERE notIn(properties.bar, tuple('a', 'b')) LIMIT 50000
-- clickhouse
SELECT replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^"|"$', '') AS foo FROM events WHERE and(equals(events.team_id, <TEAM>), ifNull(notIn(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_1)s), ''), 'null'), '^"|"$', ''), tuple(%(hogql_val_2)s, %(hogql_val_3)s)), 1)) LIMIT 50000
-- postgres
SELECT (events.properties) ->> 'foo' AS "properties.foo" FROM events WHERE ((events.properties) ->> 'bar' NOT IN (%(hogql_val_0)s, %(hogql_val_1)s)) LIMIT 50000
-- duckdb
SELECT (events.properties) ->> 'foo' AS "properties.foo" FROM events WHERE ((events.properties) ->> 'bar' NOT IN (%(hogql_val_0)s, %(hogql_val_1)s)) LIMIT 50000

#### compare_range_gt  —  range comparison
## hogql-source: SELECT properties.foo FROM events WHERE properties.bar > '5'
-- hogql
SELECT properties.foo FROM events WHERE greater(properties.bar, '5') LIMIT 50000
-- clickhouse
SELECT replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^"|"$', '') AS foo FROM events WHERE and(equals(events.team_id, <TEAM>), ifNull(greater(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_1)s), ''), 'null'), '^"|"$', ''), %(hogql_val_2)s), 0)) LIMIT 50000
-- postgres
SELECT (events.properties) ->> 'foo' AS "properties.foo" FROM events WHERE ((events.properties) ->> 'bar' > %(hogql_val_0)s) LIMIT 50000
-- duckdb
SELECT (events.properties) ->> 'foo' AS "properties.foo" FROM events WHERE ((events.properties) ->> 'bar' > %(hogql_val_0)s) LIMIT 50000

#### compare_like  —  LIKE pattern
## hogql-source: SELECT properties.foo FROM events WHERE properties.bar LIKE 'a%'
-- hogql
SELECT properties.foo FROM events WHERE like(properties.bar, 'a%') LIMIT 50000
-- clickhouse
SELECT replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^"|"$', '') AS foo FROM events WHERE and(equals(events.team_id, <TEAM>), ifNull(like(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_1)s), ''), 'null'), '^"|"$', ''), %(hogql_val_2)s), 0)) LIMIT 50000
-- postgres
SELECT (events.properties) ->> 'foo' AS "properties.foo" FROM events WHERE ((events.properties) ->> 'bar' LIKE %(hogql_val_0)s) LIMIT 50000
-- duckdb
SELECT (events.properties) ->> 'foo' AS "properties.foo" FROM events WHERE ((events.properties) ->> 'bar' LIKE %(hogql_val_0)s) LIMIT 50000

#### compare_ilike  —  case-insensitive ILIKE pattern
## hogql-source: SELECT properties.foo FROM events WHERE properties.bar ILIKE '%a%'
-- hogql
SELECT properties.foo FROM events WHERE ilike(properties.bar, '%a%') LIMIT 50000
-- clickhouse
SELECT replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^"|"$', '') AS foo FROM events WHERE and(equals(events.team_id, <TEAM>), ifNull(ilike(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_1)s), ''), 'null'), '^"|"$', ''), %(hogql_val_2)s), 0)) LIMIT 50000
-- postgres
SELECT (events.properties) ->> 'foo' AS "properties.foo" FROM events WHERE ((events.properties) ->> 'bar' ILIKE %(hogql_val_0)s) LIMIT 50000
-- duckdb
SELECT (events.properties) ->> 'foo' AS "properties.foo" FROM events WHERE ((events.properties) ->> 'bar' ILIKE %(hogql_val_0)s) LIMIT 50000

#### in_group_by  —  property in SELECT and GROUP BY
## hogql-source: SELECT properties.foo, count() FROM events GROUP BY properties.foo
-- hogql
SELECT properties.foo, count() FROM events GROUP BY properties.foo LIMIT 50000
-- clickhouse
SELECT replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^"|"$', '') AS foo, count() AS `count()` FROM events WHERE equals(events.team_id, <TEAM>) GROUP BY replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_1)s), ''), 'null'), '^"|"$', '') LIMIT 50000
-- postgres
SELECT (events.properties) ->> 'foo' AS "properties.foo", count() FROM events GROUP BY (events.properties) ->> 'foo' LIMIT 50000
-- duckdb
SELECT (events.properties) ->> 'foo' AS "properties.foo", count() FROM events GROUP BY (events.properties) ->> 'foo' LIMIT 50000

#### in_order_by  —  property in ORDER BY
## hogql-source: SELECT properties.foo FROM events ORDER BY properties.foo
-- hogql
SELECT properties.foo FROM events ORDER BY properties.foo ASC LIMIT 50000
-- clickhouse
SELECT replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^"|"$', '') AS foo FROM events WHERE equals(events.team_id, <TEAM>) ORDER BY replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_1)s), ''), 'null'), '^"|"$', '') ASC LIMIT 50000
-- postgres
SELECT (events.properties) ->> 'foo' AS "properties.foo" FROM events ORDER BY (events.properties) ->> 'foo' ASC LIMIT 50000
-- duckdb
SELECT (events.properties) ->> 'foo' AS "properties.foo" FROM events ORDER BY (events.properties) ->> 'foo' ASC LIMIT 50000

#### in_having  —  property in HAVING
## hogql-source: SELECT properties.foo, count() AS c FROM events GROUP BY properties.foo HAVING properties.foo != ''
-- hogql
SELECT properties.foo, count() AS c FROM events GROUP BY properties.foo HAVING notEquals(properties.foo, '') LIMIT 50000
-- clickhouse
SELECT replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^"|"$', '') AS foo, count() AS c FROM events WHERE equals(events.team_id, <TEAM>) GROUP BY replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_1)s), ''), 'null'), '^"|"$', '') HAVING ifNull(notEquals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_2)s), ''), 'null'), '^"|"$', ''), %(hogql_val_3)s), 1) LIMIT 50000
-- postgres
SELECT (events.properties) ->> 'foo' AS "properties.foo", count() AS c FROM events GROUP BY (events.properties) ->> 'foo' HAVING ((events.properties) ->> 'foo' != %(hogql_val_0)s) LIMIT 50000
-- duckdb
SELECT (events.properties) ->> 'foo' AS "properties.foo", count() AS c FROM events GROUP BY (events.properties) ->> 'foo' HAVING ((events.properties) ->> 'foo' != %(hogql_val_0)s) LIMIT 50000

#### in_cte  —  property inside a CTE body — the visitor-coverage gap that the suite-wide oracle caught (doc §3.2)
## hogql-source: WITH recent AS (SELECT uuid FROM events WHERE properties.foo = 'x') SELECT uuid FROM recent
-- hogql
WITH recent AS (SELECT uuid FROM events WHERE equals(properties.foo, 'x')) SELECT uuid FROM recent LIMIT 50000
-- clickhouse
WITH recent AS (SELECT events.uuid AS uuid FROM events WHERE and(equals(events.team_id, <TEAM>), ifNull(equals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^"|"$', ''), %(hogql_val_1)s), 0))) SELECT recent.uuid AS uuid FROM recent LIMIT 50000
-- postgres
WITH recent AS (SELECT events.uuid FROM events WHERE ((events.properties) ->> 'foo' = %(hogql_val_0)s)) SELECT recent.uuid FROM recent LIMIT 50000
-- duckdb
WITH recent AS (SELECT events.uuid FROM events WHERE ((events.properties) ->> 'foo' = %(hogql_val_0)s)) SELECT recent.uuid FROM recent LIMIT 50000

#### in_subquery  —  property inside a nested subquery
## hogql-source: SELECT uuid FROM (SELECT uuid, properties.foo AS f FROM events) WHERE f = 'x'
-- hogql
SELECT uuid FROM (SELECT uuid, properties.foo AS f FROM events) WHERE equals(f, 'x') LIMIT 50000
-- clickhouse
SELECT uuid AS uuid FROM (SELECT events.uuid AS uuid, replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^"|"$', '') AS f FROM events WHERE equals(events.team_id, <TEAM>)) WHERE ifNull(equals(f, %(hogql_val_1)s), 0) LIMIT 50000
-- postgres
SELECT uuid FROM (SELECT events.uuid, (events.properties) ->> 'foo' AS f FROM events) WHERE (f = %(hogql_val_0)s) LIMIT 50000
-- duckdb
SELECT uuid FROM (SELECT events.uuid, (events.properties) ->> 'foo' AS f FROM events) WHERE (f = %(hogql_val_0)s) LIMIT 50000
