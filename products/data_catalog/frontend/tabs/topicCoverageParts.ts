import type { TopicCoverageApi } from '../generated/api.schemas'

// These colors pass the color-blind checks as an ordered set, so change them together.
export const TOPIC_COVERAGE_PARTS: { key: keyof TopicCoverageApi; label: string; colorVar: string }[] = [
    { key: 'metric', label: 'Found a metric that fits', colorVar: 'data-color-5' },
    { key: 'table', label: 'No metric, but found a table', colorVar: 'data-color-14' },
    { key: 'nothing', label: 'Found nothing', colorVar: 'data-color-1' },
]
