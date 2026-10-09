import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconArrowRight, IconSparkles, IconX } from '@posthog/icons'
import { LemonCard, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { Experiment } from '~/types'

import { experimentScannerParams } from 'products/replay_vision/frontend/replay_scanners/experimentTargeting'
import { scannerTypeLabel } from 'products/replay_vision/frontend/replay_scanners/types'

import { LinkedScanner, experimentReplayTabLogic } from './experimentReplayTabLogic'
import { VariantTag } from './VariantTag'

/** Where an experiment scanner's own results are: its Variants tab. Other types open on their default tab. */
function scannerUrl(scanner: LinkedScanner): string {
    return scanner.scannerType === 'experiment'
        ? combineUrl(urls.replayVision(scanner.id), { tab: 'variants' }).url
        : urls.replayVision(scanner.id)
}

/** Holds the card's place while the lookup is in flight, so the tab doesn't flash the set-up card first. */
function ScannerEntryPointSkeleton(): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="mb-2 p-3" data-attr="experiment-recordings-linked-scanners-loading">
            <LemonSkeleton className="mb-2 h-5 w-64" />
            <LemonSkeleton className="h-4 w-full" repeat={2} />
        </LemonCard>
    )
}

/** The scanners already watching this experiment, each with a link to its results. */
function LinkedScannersCard({
    scanners,
    addUrl,
    onAdd,
    onOpen,
}: {
    scanners: LinkedScanner[]
    addUrl: string
    onAdd: () => void
    onOpen: (scanner: LinkedScanner) => void
}): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="mb-2 p-0" data-attr="experiment-recordings-linked-scanners">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
                <span className="flex items-center gap-2 font-semibold">
                    <IconSparkles className="text-ai" />
                    Replay vision scanners on this experiment
                </span>
                <LemonButton
                    type="secondary"
                    size="small"
                    to={addUrl}
                    onClick={() => onAdd()}
                    data-attr="experiment-recordings-scanner-add-another"
                >
                    Add scanner
                </LemonButton>
            </div>
            <ul className="m-0 list-none divide-y p-0">
                {scanners.map((scanner) => (
                    <li key={scanner.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                        <span className="flex min-w-0 items-center gap-2">
                            <Link
                                to={scannerUrl(scanner)}
                                onClick={() => onOpen(scanner)}
                                className="truncate font-medium"
                            >
                                {scanner.name}
                            </Link>
                            <LemonTag type="muted">{scannerTypeLabel(scanner.scannerType)}</LemonTag>
                            {scanner.startsAtLaunch && <LemonTag type="highlight">Starts at launch</LemonTag>}
                        </span>
                        <span className="flex shrink-0 items-center gap-3">
                            <span className="text-xs text-muted">
                                {pluralize(scanner.observationsThisMonth, 'observation')} this month
                            </span>
                            {scanner.scannerType === 'experiment' && (
                                <LemonButton
                                    type="tertiary"
                                    size="xsmall"
                                    sideIcon={<IconArrowRight />}
                                    to={scannerUrl(scanner)}
                                    onClick={() => onOpen(scanner)}
                                    data-attr="experiment-recordings-scanner-compare-variants"
                                >
                                    Compare variants
                                </LemonButton>
                            )}
                        </span>
                    </li>
                ))}
            </ul>
        </LemonCard>
    )
}

/** Offers an experiment scanner on an experiment that has none yet. A dismissal hides it on every experiment. */
function ScannerSetUpCard({
    variantKeys,
    setUpUrl,
    onSetUp,
    onDismiss,
}: {
    variantKeys: string[]
    setUpUrl: string
    onSetUp: () => void
    onDismiss: () => void
}): JSX.Element {
    return (
        <LemonCard
            hoverEffect={false}
            className="@container relative mb-2 p-4"
            data-attr="experiment-recordings-scanner-cross-sell-card"
        >
            <LemonButton
                className="absolute top-2 right-2"
                size="xsmall"
                icon={<IconX />}
                onClick={() => onDismiss()}
                tooltip="Hide this suggestion"
                aria-label="Dismiss"
                data-attr="experiment-recordings-scanner-cross-sell-dismiss"
            />
            <div className="flex flex-col gap-3 pr-8 @2xl:flex-row @2xl:items-center @2xl:justify-between">
                <div className="min-w-0 space-y-1">
                    <h3 className="m-0 flex items-center gap-2 text-base font-semibold">
                        <IconSparkles className="text-ai" />
                        Compare what users do in each variant
                    </h3>
                    <p className="m-0 text-sm text-secondary">
                        An experiment scanner uses Replay vision to summarize the recordings of exposed users, then
                        shows each variant side by side. Use it next to your metrics to see how people use what you
                        changed.
                    </p>
                    {variantKeys.length > 0 && (
                        <div className="flex flex-wrap items-center gap-1 pt-1 text-xs text-muted">
                            <span>Watches</span>
                            {variantKeys.map((key) => (
                                <VariantTag key={key} variantKey={key} />
                            ))}
                        </div>
                    )}
                </div>
                <div className="flex shrink-0 flex-col items-start gap-1 @2xl:items-end">
                    <LemonButton
                        type="primary"
                        to={setUpUrl}
                        onClick={() => onSetUp()}
                        data-attr="experiment-recordings-scanner-cross-sell"
                    >
                        Set up experiment scanner
                    </LemonButton>
                    <span className="text-xs text-muted">Each summarized session uses Replay vision credits.</span>
                </div>
            </div>
        </LemonCard>
    )
}

/**
 * Replay vision's entry point on an experiment's Recordings tab: the scanners already watching the
 * experiment, or an offer to set one up. Rendered only behind the experiment scanner flag.
 */
export function ExperimentScannerEntryPoint({
    experiment,
    variantKey,
}: {
    experiment: Experiment
    /** The variant the list is narrowed to, carried into the wizard so the scanner starts on it. */
    variantKey: string | null
}): JSX.Element | null {
    const logic = experimentReplayTabLogic({ experiment })
    const { linkedScanners, linkedScannersLoading, variantKeys, scannerSetUpDismissed } = useValues(logic)
    const { scannerCrossSellClicked, dismissScannerSetUp, linkedScannerOpened } = useActions(logic)

    const setUpUrl = combineUrl(
        urls.replayVisionScannerTemplate('new'),
        experimentScannerParams({ experimentId: experiment.id as number, variantKey })
    ).url

    if (linkedScannersLoading) {
        return <ScannerEntryPointSkeleton />
    }
    if (linkedScanners.length > 0) {
        return (
            <LinkedScannersCard
                scanners={linkedScanners}
                addUrl={setUpUrl}
                onAdd={scannerCrossSellClicked}
                onOpen={(scanner) => linkedScannerOpened(scanner.scannerType)}
            />
        )
    }
    if (scannerSetUpDismissed) {
        return null
    }
    return (
        <ScannerSetUpCard
            variantKeys={variantKeys}
            setUpUrl={setUpUrl}
            onSetUp={scannerCrossSellClicked}
            onDismiss={dismissScannerSetUp}
        />
    )
}
