const Sequencer = require('@jest/test-sequencer').default
const fs = require('fs')
const path = require('path')

const TIMINGS_PATH = path.join(__dirname, 'jest-timings.json')

function loadTimings() {
    try {
        return JSON.parse(fs.readFileSync(TIMINGS_PATH, 'utf8'))
    } catch {
        return null
    }
}

function relativePath(test) {
    return path.posix.relative(
        test.context.config.rootDir.split(path.sep).join(path.posix.sep),
        test.path.split(path.sep).join(path.posix.sep)
    )
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

function partition(entries, shardCount) {
    const byKey = [...entries].sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0))
    const known = byKey.filter((entry) => entry.duration !== null).sort((a, b) => b.duration - a.duration)
    const unknown = byKey.filter((entry) => entry.duration === null)
    const median = known.length > 0 ? known[Math.floor(known.length / 2)].duration : 10
    const totals = new Array(shardCount).fill(0)
    const shards = Array.from({ length: shardCount }, () => [])
    for (const entry of known) {
        const index = lightestShard(totals)
        shards[index].push(entry.item)
        totals[index] += entry.duration
    }
    for (const entry of unknown) {
        const index = lightestShard(totals)
        shards[index].push(entry.item)
        totals[index] += median
    }
    return shards
}

class TimingBalancedSequencer extends Sequencer {
    shard(tests, options) {
        const timings = loadTimings()
        if (!timings) {
            return super.shard(tests, options)
        }
        const entries = tests.map((test) => {
            const key = relativePath(test)
            return { key, duration: typeof timings[key] === 'number' ? timings[key] : null, item: test }
        })
        return partition(entries, options.shardCount)[options.shardIndex - 1]
    }
}

module.exports = TimingBalancedSequencer
module.exports.partition = partition
