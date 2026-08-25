// Sizes the Django shards of a narrowed (test-selection) run in ci-backend.yml.
//
// Reads the shadow selector's JSON and applies turbo-discover's calculateShards
// to the selected tests' recorded seconds, so a narrowed segment gets the same
// per-shard budget as the full matrix — target wall clock, per-segment overhead,
// safety factor and cap all stay defined in turbo-discover.js. Sizing from the
// selection's own recorded seconds also keeps a skewed selection honest: picking
// the heavy half of a segment costs more shards than picking the light half.
//
// The floor is 1 instead of DJANGO_MIN_SHARDS: a narrow selection should stay a
// single job. Anything missing or unreadable degrades to 1 shard per segment,
// which is what the matrix assumed for every narrowed run before this existed.
//
// Usage: node selected-django-shards.js /tmp/selection.json
// Prints e.g. {"core":1,"poe":1,"temporal":6}

const fs = require('fs')
const path = require('path')
const { calculateShards, DJANGO_OVERHEAD_SECONDS_BY_SEGMENT } = require(path.join(__dirname, 'turbo-discover.js'))

// Selector segment key -> Django matrix segment name.
const MATRIX_NAME_BY_SEGMENT = { core: 'Core', poe: 'CorePOE', temporal: 'Temporal' }

function selectedShards(selection) {
    const seconds = selection?.durations?.selected_seconds_by_segment ?? {}
    const shards = {}
    for (const [segment, matrixName] of Object.entries(MATRIX_NAME_BY_SEGMENT)) {
        const overhead = DJANGO_OVERHEAD_SECONDS_BY_SEGMENT[matrixName]
        shards[segment] = calculateShards(Number(seconds[segment]) || 0, overhead, 1)
    }
    return shards
}

module.exports = { selectedShards }

if (require.main === module) {
    let selection = {}
    try {
        selection = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'))
    } catch {
        // Fall through to the 1-shard-per-segment default.
    }
    process.stdout.write(JSON.stringify(selectedShards(selection)))
}
