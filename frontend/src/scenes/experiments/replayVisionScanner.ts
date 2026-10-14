import type { Experiment } from '~/types'

import type { ReplayScannerApi } from 'products/replay_vision/frontend/generated/api.schemas'
import {
    experimentScannerConfig,
    experimentScannerQuery,
} from 'products/replay_vision/frontend/replay_scanners/experimentTargeting'
import {
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    scannerToApiBody,
} from 'products/replay_vision/frontend/replay_scanners/types'

const SCANNER_NAME_MAX_LENGTH = 255

/**
 * An experiment scanner on the experiment the wizard just created. That experiment is a draft, so
 * the scanner is saved off with `start_on_launch`, and the backend turns it on when the experiment
 * launches. `query` carries only the experiment's test-account setting: the API derives the
 * exposed population from the experiment at scan time.
 */
export function experimentScannerBody(experiment: Experiment): ReplayScannerApi {
    const nameSuffix = ` (#${experiment.id})`
    const name = `${experiment.name.slice(0, SCANNER_NAME_MAX_LENGTH - nameSuffix.length)}${nameSuffix}`

    return scannerToApiBody({
        name,
        description: 'Summarizes what participants do after they are exposed to this experiment, for each variant.',
        scanner_type: 'experiment',
        scanner_config: { ...experimentScannerConfig(experiment, null), start_on_launch: true },
        // `model` is required by the create serializer; the rest of the product picks the same defaults.
        provider: DEFAULT_PROVIDER,
        model: DEFAULT_MODEL,
        query: experimentScannerQuery(experiment),
        enabled: false,
    })
}
