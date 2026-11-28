import { translateNrql } from './nrql'

const SCOPE = "event = 'OrderPlaced' and {filters}"

describe('translateNrql', () => {
    test.each([
        ['count', 'SELECT count(*) FROM OrderPlaced', `select count() as count from events where ${SCOPE}`],
        [
            'aggregates on attributes, with aliases',
            "SELECT uniqueCount(userId) AS 'Buyers', sum(total), average(total) FROM OrderPlaced",
            `select uniqExact(properties.userId) as Buyers, sum(toFloat(properties.total)) as sum, avg(toFloat(properties.total)) as average from events where ${SCOPE}`,
        ],
        [
            'percentiles, one column each',
            'SELECT percentile(latencyMs, 50, 95) FROM OrderPlaced',
            `select quantile(0.5)(toFloat(properties.latencyMs)) as p50, quantile(0.95)(toFloat(properties.latencyMs)) as p95 from events where ${SCOPE}`,
        ],
        [
            'WHERE with strings, numbers, IN, LIKE and NULL',
            "SELECT count(*) FROM OrderPlaced WHERE plan = 'pro' AND total > 10 AND (country IN ('NL', 'DE') OR coupon LIKE '%SALE%') AND refund IS NULL",
            "select count() as count from events where event = 'OrderPlaced' and (properties.plan = 'pro' and toFloat(properties.total) > 10 and (properties.country in ('NL', 'DE') or properties.coupon ilike '%SALE%') and isNull(properties.refund)) and {filters}",
        ],
        [
            'filter() and percentage()',
            "SELECT filter(count(*), WHERE paid IS TRUE) AS 'Paid', percentage(count(*), WHERE paid = false) FROM OrderPlaced",
            `select countIf(properties.paid = true) as Paid, ((countIf(properties.paid = false)) / (count()) * 100) as percentage from events where ${SCOPE}`,
        ],
        [
            'arithmetic between aggregates and inside them',
            "SELECT sum(total) / count(*) AS 'Avg order', percentile(durationS / 60, 95) FROM OrderPlaced",
            `select sum(toFloat(properties.total)) / count() as \`Avg order\`, quantile(0.95)(toFloat(toFloat(properties.durationS) / 60)) as percentile from events where ${SCOPE}`,
        ],
        [
            'FACET with LIMIT, ordered by the first value',
            "SELECT count(*) AS 'Orders %' FROM OrderPlaced FACET plan, `shop.region` LIMIT 5",
            `select properties.plan as plan, properties.\`shop.region\` as region, count() as \`Orders percent\` from events where ${SCOPE} group by plan, region order by \`Orders percent\` desc limit 5`,
        ],
        [
            'several event types, faceted by eventType()',
            'SELECT count(*) FROM OrderPlaced, OrderRefunded FACET eventType()',
            "select event as facet, count() as count from events where event in ('OrderPlaced', 'OrderRefunded') and {filters} group by facet order by count desc limit 10",
        ],
        [
            'FACET cases()',
            "SELECT count(*) FROM OrderPlaced FACET cases(WHERE total < 10 AS 'Small', WHERE total >= 10 AS 'Large')",
            "select multiIf(toFloat(properties.total) < 10, 'Small', toFloat(properties.total) >= 10, 'Large', null) as facet, count() as count from events where event = 'OrderPlaced' and isNotNull(multiIf(toFloat(properties.total) < 10, 'Small', toFloat(properties.total) >= 10, 'Large', null)) and {filters} group by facet order by count desc limit 10",
        ],
        [
            'percentage() inside arithmetic keeps its precedence',
            'SELECT 100 / percentage(count(*), WHERE paid = true) FROM OrderPlaced',
            `select 100 / ((countIf(properties.paid = true)) / (count()) * 100) as value from events where ${SCOPE}`,
        ],
        [
            'filter() on an attribute count with an OR condition',
            "SELECT filter(count(userId), WHERE paid = true OR plan = 'pro') FROM OrderPlaced",
            `select countIf(isNotNull(properties.userId) and (properties.paid = true or properties.plan = 'pro')) as filter from events where ${SCOPE}`,
        ],
        [
            'TIMESERIES with an interval',
            'SELECT count(*) FROM OrderPlaced TIMESERIES 15 minutes',
            `select toStartOfInterval(timestamp, toIntervalMinute(15)) as time, count() as count from events where ${SCOPE} group by time order by time`,
        ],
        [
            'TIMESERIES AUTO picks the bucket from SINCE',
            'SELECT count(*) FROM OrderPlaced TIMESERIES AUTO SINCE 30 days ago',
            `select toStartOfDay(timestamp) as time, count() as count from events where ${SCOPE} group by time order by time`,
        ],
        [
            'TIMESERIES with FACET keeps the top facets',
            'SELECT count(*) FROM OrderPlaced FACET plan TIMESERIES 1 hour LIMIT 3',
            `select toStartOfInterval(timestamp, toIntervalHour(1)) as time, properties.plan as plan, count() as count from events where ${SCOPE} and properties.plan in (select properties.plan from events where ${SCOPE} group by properties.plan order by count() desc limit 3) group by time, plan order by time`,
        ],
        [
            'TIMESERIES with FACET ranks facets by the first SELECT item',
            'SELECT sum(total) FROM OrderPlaced FACET plan TIMESERIES 1 hour LIMIT 1',
            `select toStartOfInterval(timestamp, toIntervalHour(1)) as time, properties.plan as plan, sum(toFloat(properties.total)) as sum from events where ${SCOPE} and properties.plan in (select properties.plan from events where ${SCOPE} group by properties.plan order by sum(toFloat(properties.total)) desc limit 1) group by time, plan order by time`,
        ],
        [
            'a FACET named time does not take the time bucket alias',
            'SELECT count(*) FROM OrderPlaced FACET time TIMESERIES 1 hour LIMIT 1',
            `select toStartOfInterval(timestamp, toIntervalHour(1)) as time, properties.time as time_2, count() as count from events where ${SCOPE} and properties.time in (select properties.time from events where ${SCOPE} group by properties.time order by count() desc limit 1) group by time, time_2 order by time`,
        ],
    ])('%s', (_name, nrql, hogql) => {
        expect(translateNrql(nrql)).toMatchObject({ ok: true, hogql })
    })

    test.each([
        [
            'SINCE and UNTIL',
            'SELECT count(*) FROM OrderPlaced SINCE 2 weeks ago UNTIL 1 day ago',
            { from: 'now-2w', to: 'now-1d' },
        ],
        ['SINCE alone', 'SELECT count(*) FROM OrderPlaced SINCE 30 minutes ago', { from: 'now-30m', to: 'now' }],
        ['no SINCE', 'SELECT count(*) FROM OrderPlaced', undefined],
    ])('reads the time range from %s', (_name, nrql, since) => {
        const result = translateNrql(nrql)
        expect(result.ok && result.since).toEqual(since ?? undefined)
    })

    test.each([
        [
            'a subquery in WHERE',
            'SELECT count(*) FROM OrderPlaced WHERE userId IN (SELECT uniques(userId) FROM Signup)',
            'subquery',
        ],
        ['New Relic metrics', 'SELECT average(cpuPercent) FROM Metric', 'New Relic metrics'],
        ['COMPARE WITH', 'SELECT count(*) FROM OrderPlaced COMPARE WITH 1 week ago', 'COMPARE WITH'],
        ['an unknown function', "SELECT count(*) FROM OrderPlaced FACET capture(url, 'x')", 'capture()'],
        ['raw rows', 'SELECT userId FROM OrderPlaced', 'without an aggregate'],
        ['an empty SELECT', 'SELECT FROM OrderPlaced FACET host', 'SELECT is empty'],
        ['an inherited object name', 'SELECT __proto__(x) FROM OrderPlaced', '__proto__()'],
        ['constructor()', 'SELECT constructor(x) FROM OrderPlaced', 'constructor()'],
    ])('fails with a reason for %s', (_name, nrql, reason) => {
        const result = translateNrql(nrql)
        expect(result.ok).toBe(false)
        expect(!result.ok && result.reason).toContain(reason)
    })
})
