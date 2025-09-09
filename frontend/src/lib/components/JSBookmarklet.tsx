import { useActions } from 'kea'
import { useEffect, useRef } from 'react'

import { IconBookmarkBorder } from 'lib/lemon-ui/icons'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { TeamBasicType } from '~/types'

export function JSBookmarklet({ team }: { team: TeamBasicType }): JSX.Element {
    const initCall = `posthog.init('${
        team?.api_token
    }',{api_host:'${apiHostOrigin()}', loaded: () => alert('PostHog is now tracking events!')})`
    const href = `javascript:(function()%7Bif%20(window.posthog)%20%7Balert(%22Error%3A%20PostHog%20already%20is%20installed%20on%20this%20site%22)%7D%20else%20%7B!function(t%2Ce)%7Bvar%20o%2Cn%2Cp%2Cr%3Be.__SV%7C%7C(window.posthog%3De%2Ce._i%3D%5B%5D%2Ce.init%3Dfunction(i%2Cs%2Ca)%7Bfunction%20g(t%2Ce)%7Bvar%20o%3De.split(%22.%22)%3B2%3D%3Do.length%26%26(t%3Dt%5Bo%5B0%5D%5D%2Ce%3Do%5B1%5D)%2Ct%5Be%5D%3Dfunction()%7Bt.push(%5Be%5D.concat(Array.prototype.slice.call(arguments%2C0)))%7D%7D(p%3Dt.createElement(%22script%22)).type%3D%22text%2Fjavascript%22%2Cp.async%3D!0%2Cp.src%3Ds.api_host%2B%22%2Fstatic%2Farray.js%22%2C(r%3Dt.getElementsByTagName(%22script%22)%5B0%5D).parentNode.insertBefore(p%2Cr)%3Bvar%20u%3De%3Bfor(void%200!%3D%3Da%3Fu%3De%5Ba%5D%3D%5B%5D%3Aa%3D%22posthog%22%2Cu.people%3Du.people%7C%7C%5B%5D%2Cu.toString%3Dfunction(t)%7Bvar%20e%3D%22posthog%22%3Breturn%22posthog%22!%3D%3Da%26%26(e%2B%3D%22.%22%2Ba)%2Ct%7C%7C(e%2B%3D%22%20(stub)%22)%2Ce%7D%2Cu.people.toString%3Dfunction()%7Breturn%20u.toString(1)%2B%22.people%20(stub)%22%7D%2Co%3D%22capture%20identify%20alias%20people.set%20people.set_once%20set_config%20register%20register_once%20unregister%20opt_out_capturing%20has_opted_out_capturing%20opt_in_capturing%20reset%20isFeatureEnabled%20onFeatureFlags%22.split(%22%20%22)%2Cn%3D0%3Bn%3Co.length%3Bn%2B%2B)g(u%2Co%5Bn%5D)%3Be._i.push(%5Bi%2Cs%2Ca%5D)%7D%2Ce.__SV%3D1)%7D(document%2Cwindow.posthog%7C%7C%5B%5D)%3B${encodeURIComponent(
        initCall
    )}%7D%7D)()`

    const { reportBookmarkletDragged } = useActions(eventUsageLogic)
    const ref = useRef<HTMLAnchorElement>(null)

    useEffect(() => {
        // React cleverly stops js links from working, so we need to set the href manually
        ref.current?.setAttribute('href', href)
    }, [ref.current, href])

    return (
        <>
            {/* eslint-disable-next-line react/forbid-elements */}
            <a
                ref={ref}
                className="w-full bg-primary-alt-highlight rounded-lg justify-center p-4 flex font-bold gap-2 items-center"
                onDragStart={reportBookmarkletDragged}
            >
                <IconBookmarkBorder fontSize="1.5rem" />
                <span className="text-base">PostHog Bookmarklet</span>
            </a>
            <p className="text-center text-secondary font-medium mt-2">
                Drag to your bookmarks. Do not click on this link. The bookmarklet only works for the current browser
                session.
            </p>
        </>
    )
}
