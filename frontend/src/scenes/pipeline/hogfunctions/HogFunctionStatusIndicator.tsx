import { TZLabel } from '@posthog/apps-common'
import { LemonDropdown, LemonTable, LemonTag, LemonTagProps } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { dayjs } from 'lib/dayjs'

import { HogWatcherState } from '~/types'

import { hogFunctionConfigurationLogic } from './hogFunctionConfigurationLogic'

type DisplayOptions = { tagType: LemonTagProps['type']; display: string; description: JSX.Element }
const displayMap: Record<HogWatcherState, DisplayOptions> = {
    [HogWatcherState.healthy]: {
        tagType: 'success',
        display: 'Healthy',
        description: <>The function is running as expected.</>,
    },
    [HogWatcherState.overflowed]: {
        tagType: 'caution',
        display: 'Degraded',
        description: (
            <>
                The function is running slow or has issues performing async requests. It has been moved to the slow lane
                and may be processing slower than usual.
            </>
        ),
    },
    [HogWatcherState.disabledForPeriod]: {
        tagType: 'danger',
        display: 'Disabled temporarily',
        description: (
            <>
                The function has been disabled temporarily due to enough slow or failed requests. It will be re-enabled
                soon.
            </>
        ),
    },
    [HogWatcherState.disabledIndefinitely]: {
        tagType: 'danger',
        display: 'Disabled',
        description: (
            <>
                The function has been disabled indefinitely due to too many slow or failed requests. Please check your
                config. Updating your function will move it back to the "degraded" state for testing. If it performs
                well, it will then be moved to the healthy.
            </>
        ),
    },
}

const DEFAULT_DISPLAY: DisplayOptions = {
    tagType: 'default',
    display: 'Unknown',
    description: (
        <>The function status is unknown. The status will be derived once enough invocations have been performed.</>
    ),
}

export function HogFunctionStatusIndicator(): JSX.Element | null {
    const { hogFunction } = useValues(hogFunctionConfigurationLogic)

    if (!hogFunction || !hogFunction.enabled) {
        return null
    }

    const { tagType, display, description } = hogFunction.status?.state
        ? displayMap[hogFunction.status.state]
        : DEFAULT_DISPLAY

    const noRatings = hogFunction.status?.ratings.length === 0

    const averageRating = hogFunction.status?.ratings.length
        ? hogFunction.status.ratings.reduce((acc, x) => acc + x.rating, 0) / hogFunction.status.ratings.length
        : 0

    return (
        <LemonDropdown
            overlay={
                <>
                    <div className="p-2 space-y-2">
                        <h2 className="flex items-center m-0 gap-2">
                            Function status - <LemonTag type={tagType}>{display}</LemonTag>
                        </h2>

                        <p>
                            Your function has{' '}
                            {noRatings ? (
                                <>
                                    no ratings yet. There are either no recent invocations or data is still being
                                    gathered.
                                </>
                            ) : (
                                <>
                                    a rating of <b>{Math.round(averageRating * 100)}%</b>.
                                </>
                            )}{' '}
                            A rating of 100% means the function is running perfectly, with 0% meaning it is failing
                            every time.
                        </p>

                        <p>{description}</p>

                        <h4>History</h4>
                        <ul>
                            <LemonTable
                                columns={[
                                    {
                                        title: 'Timestamp',
                                        key: 'timestamp',
                                        render: (_, { timestamp }) => <TZLabel time={dayjs(timestamp)} />,
                                    },
                                    {
                                        title: 'Status',
                                        key: 'state',
                                        render: (_, { state }) => {
                                            const { tagType, display } = displayMap[state] || DEFAULT_DISPLAY
                                            return <LemonTag type={tagType}>{display}</LemonTag>
                                        },
                                    },
                                ]}
                                dataSource={hogFunction.status?.states ?? []}
                            />
                        </ul>
                    </div>
                </>
            }
        >
            <LemonTag type={tagType}>{display}</LemonTag>
        </LemonDropdown>
    )
}
