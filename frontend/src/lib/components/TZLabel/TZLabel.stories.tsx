import { Meta } from '@storybook/react'
import { useState } from 'react'

import { TZLabel } from 'lib/components/TZLabel/index'
import { now } from 'lib/dayjs'
import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

import { mswDecorator } from '~/mocks/browser'

const meta: Meta<typeof TZLabel> = {
    title: 'Components/TZ Label',
    component: TZLabel,
    parameters: {
        mockDate: '2023-02-01',
    },
    decorators: [mswDecorator({})],
}
export default meta

export function Recent(): JSX.Element {
    return <TZLabel time={now()} />
}

export function MoreThanADayAgo(): JSX.Element {
    return <TZLabel time={now().subtract(2, 'day')} />
}

export function AbsoluteTimestamp(): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <div>
                <strong>Relative (default):</strong> <TZLabel time={now()} />
            </div>
            <div>
                <strong>Absolute:</strong> <TZLabel time={now()} timestampStyle="absolute" />
            </div>
        </div>
    )
}

export function WithDisplayTimezone(): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <div>
                <strong>UTC:</strong>{' '}
                <TZLabel time={now()} displayTimezone="UTC" formatDate="YYYY-MM-DD" formatTime="HH:mm:ss" />
            </div>
            <div>
                <strong>America/New_York:</strong>{' '}
                <TZLabel
                    time={now()}
                    displayTimezone="America/New_York"
                    formatDate="YYYY-MM-DD"
                    formatTime="HH:mm:ss"
                />
            </div>
            <div>
                <strong>Asia/Tokyo:</strong>{' '}
                <TZLabel time={now()} displayTimezone="Asia/Tokyo" formatDate="YYYY-MM-DD" formatTime="HH:mm:ss" />
            </div>
            <div>
                <strong>No displayTimezone (local):</strong>{' '}
                <TZLabel time={now()} formatDate="YYYY-MM-DD" formatTime="HH:mm:ss" />
            </div>
        </div>
    )
}

export function MoreThanADayAgoWithPopover(): JSX.Element {
    return <TZLabel time={now().subtract(2, 'day')} showPopover={false} />
}

export function WithMoreThanOne(): JSX.Element {
    /**
     * really exists as a regression test...
     * each TZLabel was causing its own `<div id=":rn:" data-floating-ui-portal=""></div>` to be added to the DOM
     * with enough of these, the browser would slow down
     * */

    const [portalCount, setPortalCount] = useState(0)

    // Run this effect only once the component has mounted
    useDelayedOnMountEffect(() => {
        const count = document.querySelectorAll('[data-floating-ui-portal]').length
        setPortalCount(count)
    })

    return (
        <div className="flex flex-col gap-2">
            <h1>This is a regression test</h1>
            <p>it checks we don't add a floating portal to the DOM for every TZLabel</p>
            <LemonDivider />
            <TZLabel time={now().subtract(0, 'day')} />
            <TZLabel time={now().subtract(1, 'day')} />
            <TZLabel time={now().subtract(2, 'day')} />
            <LemonDivider />
            <div className="flex flex-row gap-1">
                <span>there are</span>
                {portalCount}
                <span>floating-ui portals in the DOM</span>
            </div>
            <div>there should be 0!</div>
        </div>
    )
}
