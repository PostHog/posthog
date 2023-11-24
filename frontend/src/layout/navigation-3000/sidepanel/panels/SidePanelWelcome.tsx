import { IconInfo, IconNight, IconNotebook, IconSearch } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { KeyboardShortcut } from '../../components/KeyboardShortcut'
import { sidePanelStateLogic } from '../sidePanelStateLogic'

export const SidePanelWelcome = (): JSX.Element => {
    const { closeSidePanel } = useActions(sidePanelStateLogic)

    useEffect(() => {
        return () => {
            // Linked to the FF to ensure it isn't shown again
            posthog.capture('3000 welcome acknowledged', {
                $set: {
                    [`3000-welcome-acknowledged`]: true,
                },
            })
        }
    }, [])

    return (
        <div className="flex flex-col items-center justify-center m-4 my-10 flex-1">
            <h1 className="font-bold text-4xl text-center">
                Welcome to <span className="text-primary-3000">PostHog&nbsp;3000</span>
            </h1>

            <p className="max-w-120 text-center">
                <b>PostHog 3000</b> is the codename for our revamped user experience. It's currently in beta, and we'd
                love to hear your feedback!
            </p>
            <ul className="space-y-4">
                <li className="bg-bg-3000 border rounded p-4 flex gap-4 items-center">
                    <IconNight className="text-3xl" />
                    <div className="flex-1">
                        <h3 className="mb-0 font-semibold">Dark mode</h3>
                        <span>
                            In addition to a general refresh of our look and feel, we now have full support for dark
                            mode.
                        </span>
                    </div>
                </li>

                <li className="bg-bg-3000 border rounded p-4 flex gap-4 items-center">
                    <IconNotebook className="text-3xl" />
                    <div className="flex-1">
                        <h3 className="mb-0 font-semibold">Notebooks</h3>
                        <span>Explore your ideas, gather your data and come to conclusions in a single document.</span>
                    </div>
                </li>
                <li className="bg-bg-3000 border rounded p-4 flex gap-4 items-center">
                    <IconInfo className="text-3xl" />
                    <div className="flex-1">
                        <h3 className="mb-0 font-semibold">In-app docs</h3>
                        <span>Get contextual information from our docs without needing to leave the app.</span>
                    </div>
                </li>
                <li className="bg-bg-3000 border rounded p-4 flex gap-4 items-center">
                    <IconSearch className="text-3xl" />
                    <div className="flex-1">
                        <h3 className="mb-0 font-semibold">Global search + commands</h3>
                        <span>
                            Search from anywhere in the app simply starting by pressing <KeyboardShortcut shift k />
                        </span>
                    </div>
                </li>
            </ul>

            <LemonButton size="large" type="primary" className="mt-8" onClick={() => closeSidePanel()}>
                Get started
            </LemonButton>
        </div>
    )
}
