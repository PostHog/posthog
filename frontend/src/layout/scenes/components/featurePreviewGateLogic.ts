import {
    BreakPointFunction,
    MakeLogicType,
    actions,
    afterMount,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
} from 'kea'

import { teamLogic } from 'scenes/teamLogic'

// Alias kea so kea-typegen skips this logic - the logic type is hand-written below, because the
// props carry a probe function the generator cannot describe.
const buildKea = kea

/** How often to re-ask the server whether the flag has landed, while it answers that it hasn't. */
const POLL_MS = 1500
/**
 * Ingestion normally catches up within a couple of seconds. Past this the gate opens regardless, so
 * a probe that answers `false` forever can never lock a user out of a product they enabled: they
 * land on the scene and read its own errors, which is what happens without a probe at all.
 */
const TIMEOUT_MS = 15000

export interface FeaturePreviewGateLogicProps {
    flag: string
    /** See `FeaturePreviewGateConfig.confirmServerAccess`. Without one, the gate never waits. */
    confirmServerAccess?: () => Promise<boolean>
}

export interface FeaturePreviewGateValues {
    confirmed: boolean
    currentTeamId: number | null
}

export interface FeaturePreviewGateActions {
    confirmAccess: () => void
    setConfirmed: () => void
}

export type FeaturePreviewGateLogicType = MakeLogicType<
    FeaturePreviewGateValues,
    FeaturePreviewGateActions,
    FeaturePreviewGateLogicProps
>

function cacheKey(teamId: number, flag: string): string {
    return `ph-feature-preview-server-access/${teamId}/${flag}`
}

// localStorage can throw (private modes, disabled storage); a cache miss only costs one probe.
function readCachedAccess(teamId: number | null, flag: string): boolean {
    try {
        return !!teamId && window.localStorage.getItem(cacheKey(teamId, flag)) === '1'
    } catch {
        return false
    }
}

function writeCachedAccess(teamId: number | null, flag: string): void {
    try {
        if (teamId) {
            window.localStorage.setItem(cacheKey(teamId, flag), '1')
        }
    } catch {
        // Nothing cached; the next visit probes again.
    }
}

/**
 * Answers whether the API agrees a feature preview flag is on, which the browser can be ahead of.
 * Enrollment reaches the server as an ingested person property, so in the seconds after a user
 * turns a preview on, posthog-js already evaluates the flag as on while every request behind the
 * scene still 403s. The scene gate waits on `confirmed` instead of handing over a product whose
 * queries all fail until a reload. A confirmed answer is cached per team, so the wait is paid once.
 */
export const featurePreviewGateLogic = buildKea<FeaturePreviewGateLogicType>([
    props({} as FeaturePreviewGateLogicProps),
    key((props: FeaturePreviewGateLogicProps) => props.flag),
    path((key) => ['layout', 'scenes', 'components', 'featurePreviewGateLogic', key]),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
    actions({
        confirmAccess: true,
        setConfirmed: true,
    }),
    reducers({
        confirmed: [
            false,
            {
                setConfirmed: () => true,
            },
        ],
    }),
    listeners(({ props, values, actions }) => ({
        confirmAccess: async (_: void, breakpoint: BreakPointFunction) => {
            const confirmServerAccess = props.confirmServerAccess
            if (!confirmServerAccess) {
                actions.setConfirmed()
                return
            }
            const deadline = Date.now() + TIMEOUT_MS
            for (;;) {
                let outcome: 'confirmed' | 'denied' | 'unknown'
                try {
                    outcome = (await confirmServerAccess()) ? 'confirmed' : 'denied'
                } catch {
                    // The probe broke for a reason waiting cannot fix, so hand over to the scene
                    // and let it surface the failure.
                    outcome = 'unknown'
                }
                breakpoint()
                if (outcome === 'confirmed') {
                    writeCachedAccess(values.currentTeamId, props.flag)
                    actions.setConfirmed()
                    return
                }
                if (outcome === 'unknown' || Date.now() >= deadline) {
                    actions.setConfirmed()
                    return
                }
                await breakpoint(POLL_MS)
            }
        },
    })),
    afterMount(({ props, values, actions }) => {
        if (!props.confirmServerAccess || readCachedAccess(values.currentTeamId, props.flag)) {
            actions.setConfirmed()
            return
        }
        actions.confirmAccess()
    }),
])
