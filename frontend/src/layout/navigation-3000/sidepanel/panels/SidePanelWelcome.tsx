import './SidePanelWelcome.scss'

import { IconArrowLeft, IconEllipsis, IconExternal, IconOpenSidebar, IconX } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import featureCommandPalette from 'public/3000/3000-command-palette.png'
import featureCommandPaletteDark from 'public/3000/3000-command-palette-dark.png'
import featureDarkMode from 'public/3000/3000-dark-mode.png'
import featureNav from 'public/3000/3000-nav.png'
import featureNavDark from 'public/3000/3000-nav-dark.png'
import featureNotebooks from 'public/3000/3000-notebooks.png'
import featureNotebooksDark from 'public/3000/3000-notebooks-dark.png'
import featureSearch from 'public/3000/3000-search.png'
import featureSearchDark from 'public/3000/3000-search-dark.png'
import featureSidePanel from 'public/3000/3000-side-panel.png'
import featureSidePanelDark from 'public/3000/3000-side-panel-dark.png'
import featureToolbar from 'public/3000/3000-toolbar.png'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { SidePanelTab } from '~/types'

import { KeyboardShortcut } from '../../components/KeyboardShortcut'
import { sidePanelStateLogic } from '../sidePanelStateLogic'

const BLOG_POST_URL = 'https://posthog.com/blog/posthog-as-a-dev-tool'

type RowProps = {
    className?: string
    columns?: string
    children: React.ReactNode
}

const Row = ({ className, columns, children }: RowProps): JSX.Element => (
    // eslint-disable-next-line react/forbid-dom-props
    <div className={clsx('gap-4 grid', className)} style={{ gridTemplateColumns: columns ? columns : '100%' }}>
        {children}
    </div>
)

type CardProps = {
    children: React.ReactNode
    className?: string
}

const Card = ({ children, className }: CardProps): JSX.Element => (
    <div className={clsx('SidePanelWelcome__card border rounded-md px-4 py-3 w-full overflow-hidden', className)}>
        {children}
    </div>
)

const Title = ({ children }: { children: React.ReactNode }): JSX.Element => (
    <h3 className="mb-1 font-bold leading-5">{children}</h3>
)
const Description = ({ children }: { children: React.ReactNode }): JSX.Element => (
    <p className="text-sm opacity-75 mb-1">{children}</p>
)
const Image = ({
    src,
    alt,
    width,
    height,
    style,
}: {
    src: string
    alt: string
    width?: number | string
    height?: number | string
    style?: React.CSSProperties
    // eslint-disable-next-line react/forbid-dom-props
}): JSX.Element => <img src={src} alt={alt} width={width} height={height} style={style} className="mt-2" />

export const SidePanelWelcome = (): JSX.Element => {
    const { closeSidePanel, openSidePanel } = useActions(sidePanelStateLogic)
    const { isDarkModeOn } = useValues(themeLogic)

    return (
        <>
            <div className="flex-shrink bg-accent-3000 border-b sticky top-0 pl-4 pr-1 py-1 z-10 flex items-center">
                <div className="flex-1">
                    <strong>What's new?</strong>
                </div>
                <div className="flex-shrink">
                    <button
                        onClick={() => closeSidePanel()}
                        className="btn btn-sm btn-secondary cursor-pointer bg-transparent"
                    >
                        <IconX className="text-lg" />
                    </button>
                </div>
            </div>
            <div className="SidePanelWelcome__hero pt-4">
                <div className="mx-auto px-4 max-w-140">
                    <h1 className="font-semibold text-base mb-2 w-full">
                        👋 <span className="opacity-75">Say hello to</span>
                        <div className="text-primary-3000 text-2xl font-bold">PostHog 3000</div>
                    </h1>
                    <p className="text-sm font-medium mb-3 opacity-75">We're past 0 to 1.</p>
                    <p
                        className="text-sm font-medium mb-4 opacity-75"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ maxWidth: 'min(calc(50% - 1rem), 16rem)' }}
                    >
                        It's time to go from 1 to&nbsp;3000. And&nbsp;this is just the&nbsp;beginning…
                    </p>
                    <div className="flex">
                        <LemonButton
                            to={BLOG_POST_URL}
                            targetBlank
                            type="primary"
                            sideIcon={<IconExternal className="text-xl" />}
                            className="mb-5 self-start"
                        >
                            Read the blog post
                        </LemonButton>
                    </div>
                </div>
            </div>
            <LemonDivider className="mb-4" />
            <div className="flex flex-col px-4 pb-6 space-y-4 mx-auto max-w-140 flex-1">
                <Row>
                    <Card>
                        <Title>Dark mode</Title>
                        <Description>
                            Toggle between light and dark. Synced with your system by&nbsp;default.
                        </Description>
                        <div className="-mr-4 -mb-3">
                            <Image
                                src={featureDarkMode}
                                alt="Dark mode"
                                width="100%"
                                style={{ borderTopLeftRadius: '0.25rem' }}
                            />
                        </div>
                    </Card>
                </Row>

                <Row className="grid grid-cols-2" columns="40% calc(60% - 1.25rem)">
                    <Card>
                        <Title>Updated nav</Title>
                        <Description>Sub-products are now split out from project &&nbsp;data.</Description>
                        <div className="-mr-4 -mb-3">
                            <Image
                                src={isDarkModeOn ? featureNavDark : featureNav}
                                alt="Updated nav"
                                width="100%"
                                style={{ borderTopLeftRadius: '0.25rem' }}
                            />
                        </div>
                    </Card>
                    <Card>
                        <Title>Notebooks</Title>
                        <Description>
                            Analyze data from different angles and share results with your team - all in
                            a&nbsp;single&nbsp;document.
                        </Description>
                        <div className="-mr-4 -mb-3">
                            <Image
                                src={isDarkModeOn ? featureNotebooksDark : featureNotebooks}
                                alt="Notebooks"
                                width="100%"
                                style={{ borderTopLeftRadius: '0.25rem' }}
                            />
                        </div>
                    </Card>
                </Row>

                <Row>
                    <Card>
                        <div className="grid grid-cols-2 gap-4 items-center">
                            <div>
                                <Title>Side panel</Title>
                                <Description>
                                    It's this multipurpose thing you're looking at right&nbsp;now!
                                </Description>
                                <Description>Create notebooks, read docs, contact support, and&nbsp;more.</Description>
                            </div>
                            <div className="-mr-4 -my-3">
                                <Image
                                    src={isDarkModeOn ? featureSidePanelDark : featureSidePanel}
                                    alt="Side panel"
                                    height="100%"
                                    style={{ maxHeight: 205 }}
                                />
                            </div>
                        </div>
                    </Card>
                </Row>

                <Row className="grid grid-cols-2" columns="calc(60% - 1.25rem) 40%">
                    <Card>
                        <Title>Improved search</Title>
                        <Description>
                            Search for anything with <KeyboardShortcut command k />
                        </Description>
                        <div className="-mr-4 -mb-3">
                            <Image
                                src={isDarkModeOn ? featureSearchDark : featureSearch}
                                alt="Improved search"
                                width="100%"
                                style={{ borderTopLeftRadius: '0.25rem' }}
                            />
                        </div>
                    </Card>
                    <Card className="flex flex-col">
                        <div className="flex-1">
                            <Title>Command bar</Title>
                            <Description>
                                Navigate faster with <KeyboardShortcut command shift k />
                            </Description>
                        </div>
                        <div className="-mr-4 -mb-3 flex-shrink">
                            <Image
                                src={isDarkModeOn ? featureCommandPaletteDark : featureCommandPalette}
                                alt="Command bar"
                                width="100%"
                                style={{ borderTopLeftRadius: '0.25rem' }}
                            />
                        </div>
                    </Card>
                </Row>

                <Row>
                    <Card>
                        <Title>Toolbar redesigned</Title>
                        <Description>
                            Dark mode: on. Same features, but easier to use. And&nbsp;we&nbsp;finally put the "bar"
                            in&nbsp;"toolbar".
                        </Description>
                        <div>
                            <Image src={featureToolbar} alt="Toolbar" width={259} />
                        </div>
                    </Card>
                </Row>

                <div className="gap-4 flex">
                    <LemonButton
                        to={BLOG_POST_URL}
                        targetBlank
                        type="primary"
                        sideIcon={<IconExternal className="text-xl" />}
                    >
                        Read the blog post
                    </LemonButton>
                    <LemonButton
                        onClick={() => openSidePanel(SidePanelTab.Support, 'feedback:posthog-3000')}
                        type="secondary"
                        sideIcon={<IconOpenSidebar className="text-xl" />}
                    >
                        Share feedback
                    </LemonButton>
                </div>
                <div className="-mb-3" style={{ fontSize: 13 /* eslint-disable-line react/forbid-dom-props */ }}>
                    <IconArrowLeft className="text-base mr-2 inline" />
                    <span className="m-0">
                        <strong>Pro tip:</strong> Access this panel again from the{' '}
                        <span className="text-base font border p-1 rounded mx-1 w-6 h-6 inline-flex align-middle">
                            <IconEllipsis />
                        </span>{' '}
                        menu.
                    </span>
                </div>
            </div>
        </>
    )
}
