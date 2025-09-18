import { useValues } from 'kea'

import { IconTrending } from '@posthog/icons'
import { LemonDivider, Tooltip } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { IconTrendingDown } from 'lib/lemon-ui/icons'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { ExperimentStatsMethod } from '~/types'

import { experimentLogic } from '../../experimentLogic'

export function HowToReadTooltip(): JSX.Element {
    const { statsMethod } = useValues(experimentLogic)
    const { isDarkModeOn } = useValues(themeLogic)

    return (
        <>
            <LemonDivider vertical className="mx-2" />
            <Tooltip
                title={
                    <div className="p-2">
                        <p className="mb-3 font-semibold">Is my variant significant?</p>
                        <p className="mb-3">
                            Look at the <strong>Delta column</strong> for each variant:
                        </p>
                        <div className="mb-3 space-y-2">
                            <div className="flex items-center gap-3">
                                <span
                                    className="inline-flex items-center gap-1 w-20 font-semibold"
                                    style={{ color: isDarkModeOn ? '#388600' : 'rgb(5, 223, 114)' }}
                                >
                                    <IconTrending className="w-3 h-3" />
                                    Green
                                </span>
                                <span>Variant won</span>
                            </div>
                            <div className="flex items-center gap-3">
                                <span
                                    className="inline-flex items-center gap-1 w-20 font-semibold"
                                    style={{ color: isDarkModeOn ? '#df4b20' : 'rgb(255, 102, 102)' }}
                                >
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
                            src={
                                isDarkModeOn
                                    ? 'https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/sig_light_2_4f2a9648ec.png'
                                    : 'https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/sign_dark_2_ce4e9018ad.png'
                            }
                            width={350}
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
                            src={
                                isDarkModeOn
                                    ? statsMethod === ExperimentStatsMethod.Bayesian
                                        ? 'https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/interval_bayesian_light_cc0eab723d.png'
                                        : 'https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/interval_frequentist_light_de8a266b6f.png'
                                    : statsMethod === ExperimentStatsMethod.Bayesian
                                      ? 'https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/interval_b_1d344c42f6.png'
                                      : 'https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/interval_f_9b8ae12438.png'
                            }
                            width={350}
                            className="rounded border object-contain mb-2"
                            alt="How to read metrics"
                        />
                        <p className="text-sm mb-0">
                            <Link to="https://posthog.com/docs/experiments/analyzing-results">
                                Learn more about analyzing results
                            </Link>
                        </p>
                    </div>
                }
            >
                <span className="text-xs text-secondary cursor-help">How to read</span>
            </Tooltip>
        </>
    )
}
