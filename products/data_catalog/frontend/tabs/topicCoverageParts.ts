import type { TopicCoverageApi } from '../generated/api.schemas'

// Muted hues that pass the color-blind and contrast checks as an ordered set on light and dark surfaces, so change them together.
export const TOPIC_COVERAGE_PARTS: { key: keyof TopicCoverageApi; label: string; color: string }[] = [
    { key: 'metric', label: 'Found a metric that fits', color: '#4e925e' },
    { key: 'table', label: 'No metric, but found a table', color: '#7e65a9' },
    { key: 'nothing', label: 'Found nothing', color: '#c17842' },
]
