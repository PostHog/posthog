import { Tooltip as BaseTooltip } from '@base-ui/react/tooltip'
import { useValues } from 'kea'

import { IconTrending } from '@posthog/icons'
import { LemonDivider } from '@posthog/lemon-ui'

import { IconTrendingDown } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { ExperimentStatsMethod } from '~/types'

import intervalsBayesianDark from 'public/experiments/how-to-read/intervals-bayesian-dark.png'
import intervalsBayesianLight from 'public/experiments/how-to-read/intervals-bayesian-light.png'
import intervalsFrequentistDark from 'public/experiments/how-to-read/intervals-frequentist-dark.png'
import intervalsFrequentistLight from 'public/experiments/how-to-read/intervals-frequentist-light.png'
import significanceDark from 'public/experiments/how-to-read/significance-dark.png'
import significanceLight from 'public/experiments/how-to-read/significance-light.png'

import { experimentLogic } from '../../experimentLogic'

const SIGNIFICANCE_IMAGES = { light: significanceLight, dark: significanceDark }
const INTERVAL_IMAGES = {
    [ExperimentStatsMethod.Bayesian]: { light: intervalsBayesianLight, dark: intervalsBayesianDark },
    [ExperimentStatsMethod.Frequentist]: { light: intervalsFrequentistLight, dark: intervalsFrequentistDark },
}

export function HowToReadTooltip({ visible }: { visible?: boolean } = {}): JSX.Element {
    const { statsMethod } = useValues(experimentLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    const theme = isDarkModeOn ? 'dark' : 'light'

    return (
        <>
            <LemonDivider vertical className="mx-2" />
            {/* Local popup instead of Lemon Tooltip: the tooltip surface is inverse-themed, which
                would pair a dark panel with light-theme screenshots (and vice versa) */}
            <BaseTooltip.Root open={visible} disableHoverablePopup={false}>
                <BaseTooltip.Trigger
                    delay={300}
                    closeDelay={100}
                    render={
                        <Link
                            to="https://posthog.com/docs/experiments/analyzing-results"
                            target="_blank"
                            className="text-xs text-secondary cursor-help"
                            onClick={(e) => e.stopPropagation()}
                        >
                            How to read
                        </Link>
                    }
                />
                <BaseTooltip.Portal>
                    <BaseTooltip.Positioner
                        side="top"
                        align="center"
                        sideOffset={8}
                        className="z-[var(--z-tooltip)] max-w-sm"
                    >
                        <BaseTooltip.Popup className="bg-surface-popover text-primary rounded border shadow-md p-4 text-sm">
                            <p className="mb-3 font-semibold">Is my variant significant?</p>
                            <p className="mb-3">
                                Look at the <strong>Delta column</strong> for each variant:
                            </p>
                            <div className="mb-3 space-y-2">
                                <div className="flex items-center gap-3">
                                    <span className="inline-flex items-center gap-1 w-20 font-semibold text-success">
                                        <IconTrending className="w-3 h-3" />
                                        Green
                                    </span>
                                    <span>Variant won</span>
                                </div>
                                <div className="flex items-center gap-3">
                                    <span className="inline-flex items-center gap-1 w-20 font-semibold text-danger">
                                        <IconTrendingDown className="w-3 h-3" />
                                        Red
                                    </span>
                                    <span>Variant lost</span>
                                </div>
                                <div className="flex items-center gap-3">
                                    <span className="inline-flex items-center gap-1 w-20 font-semibold">No color</span>
                                    <span>Not statistically significant</span>
                                </div>
                            </div>
                            <img
                                src={SIGNIFICANCE_IMAGES[theme]}
                                width={340}
                                className="rounded border object-contain mb-3"
                                alt="Significance indicators example"
                            />
                            <p className="mb-3">
                                The bars show{' '}
                                {statsMethod === ExperimentStatsMethod.Bayesian
                                    ? '95% credible intervals'
                                    : '95% confidence intervals'}
                                . When an interval doesn't cross the 0% line, the result is significant.
                            </p>
                            <img
                                src={INTERVAL_IMAGES[statsMethod][theme]}
                                width={340}
                                className="rounded border object-contain mb-2"
                                alt="How to read metrics"
                            />
                            <p className="mb-0">
                                PostHog uses its own statistical methods. Results may differ from other tools.
                            </p>
                        </BaseTooltip.Popup>
                    </BaseTooltip.Positioner>
                </BaseTooltip.Portal>
            </BaseTooltip.Root>
        </>
    )
}
