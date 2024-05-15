import { useActions, useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'

export function MyReferrals(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)

    return (
        <div>
            <p>
                Refer a friend (or an enemy - more the merrier) to PostHog! When they join you both get{' '}
                <b>INSERT PERK HERE</b>
            </p>
            <div className="border rounded border-dashed p-10 font-semibold text-4xl text-center cursor-pointer bg-bg-light hover:text-accent">
                <code>{window.location.origin}/?rcode=0231908948913849</code>
            </div>
        </div>
    )
}
