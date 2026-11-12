import type { FlameNode } from './types'

type Spec = [name: string, group: string, value: number, children?: Spec[]]

function fromSpec([name, group, value, children]: Spec): FlameNode {
    return { name, group, value, children: children?.map(fromSpec) }
}

/** A sampled CPU profile of one web request, in milliseconds, grouped by package. */
export const CPU_PROFILE: FlameNode = fromSpec([
    'handle_request',
    'django',
    1240,
    [
        [
            'middleware.authenticate',
            'django',
            96,
            [
                ['session.load', 'django', 58, [['redis.get', 'redis', 41]]],
                ['jwt.decode', 'auth', 22],
            ],
        ],
        [
            'views.insights.retrieve',
            'app',
            918,
            [
                [
                    'InsightSerializer.to_representation',
                    'app',
                    188,
                    [
                        ['json.dumps', 'stdlib', 96],
                        ['Dashboard.objects.filter', 'django-orm', 61, [['psycopg.execute', 'postgres', 54]]],
                    ],
                ],
                [
                    'query_runner.run',
                    'app',
                    702,
                    [
                        ['hogql.parse', 'hogql', 64, [['antlr.parse', 'hogql', 51]]],
                        [
                            'hogql.print_ast',
                            'hogql',
                            93,
                            [
                                ['resolve_types', 'hogql', 61],
                                ['print_select', 'hogql', 24],
                            ],
                        ],
                        [
                            'clickhouse.execute',
                            'clickhouse',
                            486,
                            [
                                ['socket.recv', 'stdlib', 402],
                                ['decompress_lz4', 'clickhouse', 61],
                            ],
                        ],
                        ['cache.set', 'redis', 31, [['redis.set', 'redis', 28]]],
                        ['format_results', 'app', 18],
                    ],
                ],
            ],
        ],
        ['middleware.csp', 'django', 12],
        ['logging.emit', 'stdlib', 9],
        ['statsd.timing', 'metrics', 2.1],
        ['statsd.incr', 'metrics', 1.6],
        ['tracing.end_span', 'metrics', 1.2],
        ['gc.collect', 'stdlib', 0.8],
    ],
])

/** One LLM agent run, in milliseconds, grouped by step kind. */
export const LLM_TRACE: FlameNode = fromSpec([
    'agent.run',
    'agent',
    18400,
    [
        ['llm.plan claude-sonnet', 'llm', 3100],
        [
            'tool.search_docs',
            'tool',
            2200,
            [
                ['embeddings.create', 'llm', 380],
                ['vector_store.query', 'retrieval', 1650],
            ],
        ],
        [
            'tool.run_sql',
            'tool',
            5200,
            [
                ['llm.write_sql claude-sonnet', 'llm', 1900],
                ['clickhouse.execute', 'retrieval', 3100],
            ],
        ],
        ['llm.answer claude-sonnet', 'llm', 7600, [['stream.tokens', 'llm', 7100]]],
    ],
])

/** A call tree compared against a baseline: one path slowed, one sped up, one call is new, one is gone. */
export const DIFF_TREE: FlameNode = {
    name: 'POST /api/checkout',
    value: 640,
    baselineValue: 520,
    count: 1800,
    baselineCount: 1700,
    children: [
        { name: 'auth.verify_session', value: 38, baselineValue: 37, count: 1800, baselineCount: 1700 },
        {
            name: 'pricing.quote',
            value: 70,
            baselineValue: 118,
            count: 1800,
            baselineCount: 1700,
            children: [
                { name: 'rules.evaluate', value: 44, baselineValue: 90, count: 1800, baselineCount: 1700 },
                { name: 'currency.convert', value: 12, baselineValue: 12.5, count: 1800, baselineCount: 1700 },
            ],
        },
        {
            name: 'inventory.reserve',
            value: 96,
            baselineValue: 92,
            count: 1790,
            baselineCount: 1700,
            children: [
                { name: 'redis.lock', value: 3, baselineValue: 3, count: 1790, baselineCount: 1700 },
                { name: 'UPDATE stock', value: 0, baselineValue: 61, count: 0, baselineCount: 1700 },
            ],
        },
        {
            name: 'payments.charge',
            value: 290,
            baselineValue: 168,
            count: 1780,
            baselineCount: 1690,
            children: [
                { name: 'POST /v1/charges', value: 240, baselineValue: 150, count: 1780, baselineCount: 1690 },
                { name: 'fraud.score', value: 36, count: 1780 },
            ],
        },
        { name: 'notifications.enqueue', value: 9, baselineValue: 5, count: 6, baselineCount: 4 },
    ],
}

export const EDGE_CASE_TREE: FlameNode = {
    name: 'root',
    value: 100,
    children: [
        {
            name: 'a_function_with_an_extremely_long_name_that_cannot_possibly_fit_in_its_cell_FooBarBazQuxQuux',
            value: 40,
        },
        { name: 'zero_value_leaf', value: 0 },
        {
            name: 'children_exceed_parent',
            value: 20,
            children: [
                { name: 'concurrent_a', value: 18 },
                { name: 'concurrent_b', value: 15 },
            ],
        },
        { name: '日本語のフレーム名と絵文字 🔥🔥', value: 25 },
    ],
}
