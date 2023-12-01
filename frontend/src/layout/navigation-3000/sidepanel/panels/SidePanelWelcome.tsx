import './SidePanelWelcome.scss'

import { IconArrowLeft, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import featureCommandPalette from 'public/3000/3000-command-palette.png'
import featureCommandPaletteDark from 'public/3000/3000-command-palette-dark.png'
import featureDarkMode from 'public/3000/3000-dark-mode.png'
import featureNav from 'public/3000/3000-nav.png'
import featureNavDark from 'public/3000/3000-nav-dark.png'
import featureNotebooks from 'public/3000/3000-notebooks.png'
import featureNotebooksDark from 'public/3000/3000-notebooks-dark.png'
import featureSearch from 'public/3000/3000-search.png'
import featureSidePanel from 'public/3000/3000-side-panel.png'
import featureSidePanelDark from 'public/3000/3000-side-panel-dark.png'
import featureToolbar from 'public/3000/3000-toolbar.png'
import { useEffect } from 'react'

import { KeyboardShortcut } from '../../components/KeyboardShortcut'
import { sidePanelStateLogic } from '../sidePanelStateLogic'

const blogPostUrl = 'https://posthog.com/blog/why-redesign'

type RowProps = {
    className?: string
    columns?: string
    children: React.ReactNode
}

const Row = ({ className, columns, children }: RowProps): JSX.Element => (
    <div className={`mb-4 gap-4 grid ${className}`} style={{ gridTemplateColumns: columns ? columns : '100%' }}>
        {children}
    </div>
)

type CardProps = {
    width?: string
    children: React.ReactNode
}

const Card = ({ width, children }: CardProps): JSX.Element => (
    <div
        className={`welcome-card bg-accent-3000 border rounded-md px-4 py-3 w-full overflow-hidden ${
            width ? width : 'w-full'
        }`}
    >
        {children}
    </div>
)

const Title = ({ children }: { children: React.ReactNode }): JSX.Element => (
    <h3 className="mb-1 font-bold leading-5">{children}</h3>
)
const Description = ({ children }: { children: React.ReactNode }): JSX.Element => (
    <p className="text-sm opacity-75">{children}</p>
)

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

export const SidePanelWelcome = (): JSX.Element => {
    const { closeSidePanel } = useActions(sidePanelStateLogic)
    const { isDarkModeOn } = useValues(themeLogic)

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
        <>
            <div className="flex-shrink bg-accent-3000 border-b sticky top-0 pl-4 pr-1 py-1 z-10 flex items-center">
                <div className="flex-1">
                    <strong>Welcome to PostHog 3000</strong>
                </div>
                <div className="flex-shrink">
                    <button
                        onClick={() => closeSidePanel()}
                        className="btn btn-sm btn-secondary cursor-pointer"
                        style={{ background: 'transparent' }}
                    >
                        <IconX className="text-lg" />
                    </button>
                </div>
            </div>
            <div className="flex flex-col m-4 my-6 flex-1">
                <h1 className="font-bold text-xl mb-4 w-full">
                    Welcome to
                    <div className="text-primary-3000 text-4xl">PostHog&nbsp;3000</div>
                </h1>
                <p className="max-w-120 text-sm font-medium mb-6">
                    We're past 0 to 1. In this new version of PostHog, we're going from 1 to 3000.
                </p>
                <div className="mb-4">
                    <LemonButton to={blogPostUrl} type="primary" fullWidth={false} style={{ display: 'inline-flex' }}>
                        Read the blog post
                    </LemonButton>
                </div>

                <Row>
                    <Card>
                        <Title>Dark mode</Title>
                        <Description>Toggle between light, dark, or sync with your system</Description>
                        <div className="-mr-4 -mb-3">
                            <img src={featureDarkMode} alt="Dark mode" width="100%" />
                        </div>
                    </Card>
                </Row>

                <Row className="grid grid-cols-2" columns="40% calc(60% - 1rem)">
                    <Card>
                        <Title>Updated nav</Title>
                        <Description>Products are now split out from project & data.</Description>
                        <div className="-mr-4 -mb-3">
                            <img src={isDarkModeOn ? featureNavDark : featureNav} alt="Updated nav" width="100%" />
                        </div>
                    </Card>
                    <Card>
                        <Title>Notebooks</Title>
                        <Description>Analyze data from different angles and share results with your team.</Description>
                        <div className="-mr-4 -mb-3">
                            <img
                                src={isDarkModeOn ? featureNotebooksDark : featureNotebooks}
                                alt="Notebooks in sidebar"
                                width="100%"
                            />
                        </div>
                    </Card>
                </Row>

                <Row>
                    <Card>
                        <div className="grid grid-cols-2 gap-4 items-center">
                            <div>
                                <Title>Side panel</Title>
                                <Description>It’s this multipurpose thing you’re looking at right now!</Description>
                                <Description>Access docs, notebooks, contact support, and more.</Description>
                            </div>
                            <div className="-mr-4 -my-3">
                                <img
                                    src={isDarkModeOn ? featureSidePanelDark : featureSidePanel}
                                    alt="Side panel"
                                    height="100%"
                                    style={{ maxHeight: 205 }}
                                />
                            </div>
                        </div>
                    </Card>
                </Row>

                <Row className="grid grid-cols-2" columns="calc(60% - 1rem) 40%">
                    <Card>
                        <Title>Improved search</Title>
                        <Description>
                            Search for anything with <KeyboardShortcut command k />
                        </Description>
                        <div className="-mr-4 -mb-3">
                            <img src={featureSearch} alt="Improved search" width="100%" />
                        </div>
                    </Card>
                    <Card>
                        <Title>Command palette</Title>
                        <Description>
                            Use <KeyboardShortcut command shift k /> to navigate faster.
                        </Description>
                        <div className="-mr-4 -mb-3">
                            <img
                                src={isDarkModeOn ? featureCommandPaletteDark : featureCommandPalette}
                                alt="Command palette"
                                width="100%"
                            />
                        </div>
                    </Card>
                </Row>

                <Row>
                    <Card>
                        <Title>Toolbar</Title>
                        <Description>
                            Same functionality, but easier to look at. And we finally put the <em>bar</em> in toolbar.
                            Also dark mode.
                        </Description>
                        <div>
                            <img src={featureToolbar} alt="Toolbar" width={259} />
                        </div>
                    </Card>
                </Row>

                <div className="flex items-center gap-2 -mb-3">
                    <IconArrowLeft className="w-5 h-5" />
                    <p className="m-0">
                        <strong>Pro tip:</strong> Access this panel again from here
                    </p>
                </div>
            </div>
        </>
    )
}
