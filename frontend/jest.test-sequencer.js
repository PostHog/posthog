const Sequencer = require('@jest/test-sequencer').default
const fs = require('fs')

const TEST_CASE_PATTERN = /\b(?:it|test)(?:\.(?:each|only|skip|todo|concurrent))*\s*\(/g
const TEST_CASE_WEIGHT = 10_000

const testWeight = (test) => {
    const size = test.context.hasteFS.getSize(test.path) ?? 0
    const testCases = fs.readFileSync(test.path, 'utf8').match(TEST_CASE_PATTERN)?.length ?? 0
    return size + testCases * TEST_CASE_WEIGHT
}

class SizeBalancedSequencer extends Sequencer {
    shard(tests, { shardCount, shardIndex }) {
        const shards = Array.from({ length: shardCount }, () => [])
        const shardWeights = new Array(shardCount).fill(0)
        const testWeights = new Map(tests.map((test) => [test.path, testWeight(test)]))
        const sortedTests = [...tests].sort((first, second) => {
            return testWeights.get(second.path) - testWeights.get(first.path) || first.path.localeCompare(second.path)
        })

        for (const test of sortedTests) {
            const shard = shardWeights.indexOf(Math.min(...shardWeights))
            shards[shard].push(test)
            shardWeights[shard] += testWeights.get(test.path)
        }

        return shards[shardIndex - 1]
    }
}

module.exports = SizeBalancedSequencer
