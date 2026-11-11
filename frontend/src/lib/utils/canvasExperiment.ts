import { FEATURE_FLAGS } from 'lib/constants'
import { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

/**
 * Whether the person is in the canvas experiment, where canvases are made through the PostHog MCP server
 * and the web app only views them. Mirrors `in_canvas_experiment` in products/canvas/backend/experiment.py,
 * so keep both in step: the experiment needs the canvas-experiment flag and the Today rail flag.
 */
export function inCanvasExperiment(featureFlags: FeatureFlagsSet): boolean {
    return !!featureFlags[FEATURE_FLAGS.CANVAS_EXPERIMENT] && !!featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV]
}
