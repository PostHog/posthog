import { IconCursorClick, IconGear, IconHome, IconInfo, IconNight, IconNotebook, IconSearch } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { KeyboardShortcut } from '../../components/KeyboardShortcut'
import { sidePanelStateLogic } from '../sidePanelStateLogic'

const blogPostUrl = 'https://posthog.com/blog/why-redesign'

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
                <b>PostHog 3000</b> is the codename for our revamped user experience. You can{' '}
                <Link to={blogPostUrl}>read more about it here</Link> but the headline features you will notice are:
            </p>
            <ul className="space-y-4">
                <li className="bg-bg-3000 border rounded p-4 flex gap-4 items-center">
                    <IconNight className="text-3xl" />
                    <div className="flex-1">
                        <h3 className="mb-0 font-semibold">Colors, data density, dark mode</h3>
                        <span>
                            A general refresh of our look and feel for enhanced visibility with improved data density
                            and a dark mode option
                        </span>
                    </div>
                </li>
                <li className="bg-bg-3000 border rounded p-4 flex gap-4 items-center">
                    <IconHome className="text-3xl" />
                    <div className="flex-1">
                        <h3 className="mb-0 font-semibold">New navigation menu </h3>
                        <span>
                            Organized into two main sections: 'project & data' and 'products', collapsible for even more
                            space
                        </span>
                    </div>
                </li>
                <li className="bg-bg-3000 border rounded p-4 flex gap-4 items-center">
                    <IconInfo className="text-3xl" />
                    <div className="flex-1">
                        <h3 className="mb-0 font-semibold">Side panel</h3>
                        <span>
                            A collapsible side panel for easy access to notebooks, in-app documentation, and support
                        </span>
                    </div>
                </li>
                <li className="bg-bg-3000 border rounded p-4 flex gap-4 items-center">
                    <IconNotebook className="text-3xl" />
                    <div className="flex-1">
                        <h3 className="mb-0 font-semibold">Notebooks</h3>
                        <span>
                            A feature for aggregating multiple insights, replays, persons or anything else on a single
                            page, aiding in data exploration and team collaboration
                        </span>
                    </div>
                </li>
                <li className="bg-bg-3000 border rounded p-4 flex gap-4 items-center">
                    <IconCursorClick className="text-3xl" />
                    <div className="flex-1">
                        <h3 className="mb-0 font-semibold">Toolbar 3000</h3>
                        <span>An updated toolbar with a modern design and dark mode compatibility</span>
                    </div>
                </li>
                <li className="bg-bg-3000 border rounded p-4 flex gap-4 items-center">
                    <IconSearch className="text-3xl" />
                    <div className="flex-1">
                        <h3 className="mb-0 font-semibold">Search + commands bar</h3>
                        <span>
                            A unified feature enabling navigation to most of PostHog's built-in features using keyboard
                            shortcuts - try it with <KeyboardShortcut shift k /> for the search and{' '}
                            <KeyboardShortcut cmd shift k /> for the command bar
                        </span>
                    </div>
                </li>
                <li className="bg-bg-3000 border rounded p-4 flex gap-4 items-center">
                    <IconGear className="text-3xl" />
                    <div className="flex-1">
                        <h3 className="mb-0 font-semibold">Reorganized settings</h3>
                        <span>
                            An improved organization of the project settings page for easier access and management
                        </span>
                    </div>
                </li>
            </ul>

            <div className="flex items-center gap-2 mt-8">
                <LemonButton to={blogPostUrl} size="large" type="secondary">
                    Tell me more
                </LemonButton>
                <LemonButton size="large" type="primary" onClick={() => closeSidePanel()}>
                    Get started
                </LemonButton>
            </div>
        </div>
    )
}
