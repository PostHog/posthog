const Sequencer = require('@jest/test-sequencer').default
const path = require('path')

function loadDurations() {
    try {
        return require('./jest.serial.durations.json')
    } catch {
        return null
    }
}

function relativePath(test) {
    return path.relative(test.context.config.rootDir, test.path).split(path.sep).join('/')
}

function median(values) {
    if (values.length === 0) {
        return 1
    }
    const sorted = [...values].sort((a, b) => a - b)
    return sorted[Math.floor(sorted.length / 2)]
}

function lightestShard(totals) {
    let lightest = 0
    for (let i = 1; i < totals.length; i++) {
        if (totals[i] < totals[lightest]) {
            lightest = i
        }
    }
    return lightest
}

function balancedShard(tests, shardIndex, shardCount, durations) {
    const fallback = median(Object.values(durations))
    const weighted = tests
        .map((test) => {
            const rel = relativePath(test)
            return { test, rel, duration: durations[rel] ?? fallback }
        })
        .sort((a, b) => b.duration - a.duration || (a.rel < b.rel ? -1 : a.rel > b.rel ? 1 : 0))

    const totals = new Array(shardCount).fill(0)
    const shards = Array.from({ length: shardCount }, () => [])
    for (const { test, duration } of weighted) {
        const target = lightestShard(totals)
        shards[target].push(test)
        totals[target] += duration
    }
    return shards[shardIndex - 1]
}

class DurationBalancedSequencer extends Sequencer {
    shard(tests, options) {
        const durations = loadDurations()
        if (!durations) {
            return super.shard(tests, options)
        }
        return balancedShard(tests, options.shardIndex, options.shardCount, durations)
    }
}

module.exports = DurationBalancedSequencer
