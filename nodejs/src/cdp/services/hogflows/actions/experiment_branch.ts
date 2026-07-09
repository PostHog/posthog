import { createHash } from 'crypto'

import { HogFlowAction } from '~/cdp/schema/hogflow'

import { findNextAction } from '../hogflow-utils'
import { ActionHandler, ActionHandlerOptions, ActionHandlerResult } from './action.interface'

type Action = Extract<HogFlowAction, { type: 'experiment_branch' }>

// Mirrors LONG_SCALE in rust/feature-flags/src/flags/flag_matching_utils.rs (and the Python/SDK
// implementations). Converted through BigInt so the f64 rounding matches rust's `as f64` cast exactly.
const LONG_SCALE = Number(BigInt('0xfffffffffffffff'))

/**
 * Deterministic hash in [0, 1) — a port of `calculate_hash` from the rust feature flags service.
 * SHA1 of `{prefix}{hashedIdentifier}{salt}`, first 15 hex chars scaled by LONG_SCALE. Must stay
 * bit-identical to the rust/Python implementations so variant assignment agrees with flag evaluation.
 */
export function calculateHash(prefix: string, hashedIdentifier: string, salt: string = ''): number {
    const digest = createHash('sha1').update(`${prefix}${hashedIdentifier}${salt}`).digest('hex')
    return Number(BigInt(`0x${digest.slice(0, 15)}`)) / LONG_SCALE
}

/**
 * Port of `get_matching_variant` from the rust feature flags service: walk the variants
 * accumulating percentages and pick the bucket the hash falls into. Falls back to the last
 * variant when percentages don't sum to 100 (mirrors random_cohort_branch's rounding safety).
 */
export function getMatchingVariantIndex(variants: Action['config']['variants'], hash: number): number {
    let cumulativePercentage = 0

    for (const [index, variant] of variants.entries()) {
        cumulativePercentage += variant.percentage / 100
        if (hash < cumulativePercentage) {
            return index
        }
    }

    return variants.length - 1
}

export class ExperimentBranchHandler implements ActionHandler {
    execute({ invocation, action, result }: ActionHandlerOptions<Action>): ActionHandlerResult {
        const { variants, winner } = action.config
        const { hogFlow } = invocation

        if (variants.length === 0) {
            throw new Error('Experiment branch has no variants configured')
        }

        if (winner) {
            const winnerIndex = variants.findIndex((variant) => variant.key === winner)
            if (winnerIndex === -1) {
                throw new Error(`Winner variant '${winner}' not found in experiment branch variants`)
            }
            const nextAction = findNextAction(hogFlow, action.id, winnerIndex)
            return { nextAction, result: { variant: winner, winner_promoted: true } }
        }

        const distinctId = invocation.person?.distinct_id ?? invocation.state.event?.distinct_id
        if (!distinctId) {
            // Without a stable identity we can't assign deterministically: route to control and skip
            // the exposure event so the experiment analysis isn't polluted with unassignable entries.
            const nextAction = findNextAction(hogFlow, action.id, 0)
            return { nextAction, result: { variant: variants[0].key, exposure_skipped: true } }
        }

        const hashKey = action.config.feature_flag_key || `workflow-${hogFlow.id}-${action.id}`
        const hash = calculateHash(`${hashKey}.`, distinctId, 'variant')
        const variantIndex = getMatchingVariantIndex(variants, hash)
        const variantKey = variants[variantIndex].key

        result.capturedPostHogEvents.push({
            team_id: hogFlow.team_id,
            event: '$workflows_experiment_exposure',
            distinct_id: distinctId,
            timestamp: new Date().toISOString(),
            properties: {
                [`$feature/${hashKey}`]: variantKey,
                feature_flag: hashKey,
                variant: variantKey,
                $workflow_id: hogFlow.id,
                $workflow_action_id: action.id,
                ...(action.config.experiment_id ? { $experiment_id: action.config.experiment_id } : {}),
            },
        })

        const nextAction = findNextAction(hogFlow, action.id, variantIndex)
        return { nextAction, result: { variant: variantKey } }
    }
}
