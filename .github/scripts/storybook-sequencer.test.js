const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { test } = require('node:test')
const vm = require('node:vm')

const root = path.resolve(__dirname, '../..')
const storybook = path.join(root, 'common/storybook')
const source = fs.readFileSync(path.join(storybook, 'test-sequencer.js'), 'utf8')

function partition(index, order = ['a', 'b', 'new'], browser = 'chromium', env = {}) {
    const sandbox = {
        module: { exports: {} },
        __dirname: storybook,
        process: { env: { TEST_BROWSERS: browser, STORYBOOK_SKIP_TAGS: `test-skip,test-skip-${browser}`, ...env } },
        require: (name) => {
            if (name === '@jest/test-sequencer') {
                return { default: class {} }
            }
            if (name === 'fs') {
                return {
                    readFileSync: (file) => {
                        if (file.endsWith('storybook-timings.json')) {
                            return JSON.stringify({
                                'a.stories.tsx': { chromium: 40, webkit: 80 },
                                'b.stories.tsx': { chromium: 40, webkit: 80 },
                            })
                        }
                        if (index === null) {
                            throw new Error('index unavailable')
                        }
                        return typeof index === 'string' ? index : JSON.stringify(index)
                    },
                }
            }
            return require(name)
        },
    }
    vm.runInNewContext(source, sandbox)
    const sequencer = new sandbox.module.exports()
    const tests = order.map((name) => ({
        path: path.join(root, `${name}.stories.tsx`),
        context: { config: { rootDir: root } },
    }))
    return [1, 2].map((shardIndex) =>
        Array.from(sequencer.shard(tests, { shardCount: 2, shardIndex }), (test) => path.basename(test.path))
    )
}

function storyIndex(extra = {}) {
    const entries = {}
    for (const [file, count] of Object.entries({ a: 4, b: 4, new: 8 })) {
        for (let i = 0; i < count; i++) {
            entries[`${file}-${i}`] = { type: 'story', importPath: `../../${file}.stories.tsx`, tags: ['test'] }
        }
    }
    return { entries: { ...entries, ...extra } }
}

for (const filters of [
    { name: 'default tags', env: {}, tags: ['test'], ignored: ['dev'], skip: 'test-skip' },
    {
        name: 'custom tags',
        env: {
            STORYBOOK_INCLUDE_TAGS: ' fast , slow ',
            STORYBOOK_EXCLUDE_TAGS: ' excluded ',
            STORYBOOK_SKIP_TAGS: ' skipped ',
        },
        tags: ['fast'],
        ignored: ['fast', 'excluded'],
        skip: 'skipped',
    },
]) {
    for (const browser of ['chromium', 'webkit']) {
        test(`balances a large unmeasured suite with measured suites for ${browser} with ${filters.name}`, () => {
            const extra = {}
            for (let i = 0; i < 40; i++) {
                extra[`skipped-${i}`] = {
                    type: 'story',
                    importPath: '../../a.stories.tsx',
                    tags: [
                        ...filters.tags,
                        filters.env.STORYBOOK_SKIP_TAGS || i % 2 ? filters.skip : `test-skip-${browser}`,
                    ],
                }
                extra[`filtered-${i}`] = { type: 'story', importPath: '../../a.stories.tsx', tags: filters.ignored }
                extra[`not-included-${i}`] = { type: 'story', importPath: '../../a.stories.tsx', tags: ['dev'] }
                extra[`docs-${i}`] = { type: 'docs', importPath: '../../a.stories.tsx' }
            }
            const index = storyIndex()
            for (const entry of Object.values(index.entries)) {
                entry.tags = filters.tags
            }
            Object.assign(index.entries, extra)
            const expected = [['new.stories.tsx'], ['a.stories.tsx', 'b.stories.tsx']]
            assert.deepEqual(partition(index, undefined, browser, filters.env), expected)
            assert.deepEqual(partition(index, ['new', 'b', 'a'], browser, filters.env), expected)
        })
    }
}

for (const index of [null, 'invalid json', { entries: {} }]) {
    test(`keeps every suite when the index is ${JSON.stringify(index)}`, () => {
        assert.deepEqual(partition(index), [['a.stories.tsx', 'new.stories.tsx'], ['b.stories.tsx']])
    })
}
