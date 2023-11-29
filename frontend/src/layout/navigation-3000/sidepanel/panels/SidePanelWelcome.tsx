import { IconCursorClick, IconHome, IconInfo, IconNight, IconNotebook, IconSearch } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { KeyboardShortcut } from '../../components/KeyboardShortcut'
import { sidePanelStateLogic } from '../sidePanelStateLogic'

const blogPostUrl = 'https://posthog.com/blog/why-redesign'

type WelcomeBannerProps = {
    icon: React.ReactNode
    title: string
    description: string | JSX.Element
}

const WelcomeBanner = ({ icon, title, description }: WelcomeBannerProps): JSX.Element => (
    <li className="bg-bg-3000 border rounded-md px-4 py-3 flex gap-4 items-center">
        <div className="flex shrink-0 text-2xl">{icon}</div>
        <div className="flex-1">
            <h3 className="mb-0 font-semibold">{title}</h3>
            <span>{description}</span>
        </div>
    </li>
)

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
        <div className="flex flex-col items-center justify-center m-4 my-6 flex-1">
            <h1 className="font-bold text-4xl text-center mb-4">
                Welcome to <span className="text-primary-3000">PostHog&nbsp;3000</span>
            </h1>
            <p className="max-w-120 text-center text-sm font-medium mb-6">
                We're past zero to one.
                <br />
                In this new version of PostHog, we're going from one to 3000.
            </p>
            <ul className="space-y-2">
                <WelcomeBanner
                    icon={<IconNight />}
                    title="Light and dark mode"
                    description="We've brought the dark mode you know from our website into&nbsp;the&nbsp;app. At&nbsp;the same&nbsp;time, light mode finally follows our&nbsp;brand&nbsp;style."
                />
                <WelcomeBanner
                    icon={<IconHome />}
                    title="Revamped navigation"
                    description={
                        <>
                            The navbar is now divided into two sections: <strong>Project&nbsp;&&nbsp;data</strong>{' '}
                            and&nbsp;<strong>Products</strong>. The&nbsp;new top bar&nbsp;is sticky, so that the key
                            actions and info stay within reach.
                        </>
                    }
                />
                <WelcomeBanner
                    icon={<IconNotebook />}
                    title="Notebooks"
                    description="Explore ideas more easily than ever with PostHog notebooks. Analyze&nbsp;your data from different angles and then share findings with&nbsp;the&nbsp;team."
                />
                <WelcomeBanner
                    icon={<IconSearch />}
                    title="Search and command bar"
                    description={
                        <>
                            Search for anything in PostHog with <KeyboardShortcut command k />. Get&nbsp;things done
                            faster using the command bar under <KeyboardShortcut command shift k />.
                        </>
                    }
                />
                <WelcomeBanner
                    icon={<IconInfo />}
                    title="Side panel"
                    description="You're looking at it now. Access notebooks, support, or in-app docs while staying in&nbsp;the&nbsp;flow."
                />
                <WelcomeBanner
                    icon={<IconCursorClick />}
                    title="Toolbar 3000"
                    description={
                        <>
                            We've applied the same thinking as above to the Toolbar. It's now easier to use,
                            cleaner-looking, and finally something you can call a <i>bar</i>.
                        </>
                    }
                />
            </ul>

            <div className="flex items-center gap-2 mt-4">
                <LemonButton to={blogPostUrl} size="large" type="secondary">
                    Read the blog post
                </LemonButton>
                <LemonButton size="large" type="primary" onClick={() => closeSidePanel()}>
                    Get started
                </LemonButton>
            </div>
        </div>
    )
}
