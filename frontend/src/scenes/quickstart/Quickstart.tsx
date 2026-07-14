import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useRef } from 'react'

import { IconBook, IconCheckCircle, IconGraduationCap, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { Logomark } from 'lib/brand'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { dayjs } from 'lib/dayjs'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'
import { useInstallationComplete } from 'scenes/onboarding/legacy/sdks/hooks/useInstallationComplete'
import { useWizardCommand } from 'scenes/onboarding/shared/SetupWizardBanner'
import { getProductIcon } from 'scenes/onboarding/shared/utils'
import { SceneExport } from 'scenes/sceneTypes'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { ActivityTab, OnboardingStepKey } from '~/types'

import { QuickstartPublication } from './publications'
import { QuickstartProduct, quickstartLogic } from './quickstartLogic'

export const scene: SceneExport = {
    component: Quickstart,
    logic: quickstartLogic,
}

function captureQuickstartAction(action: string, productKey?: string): void {
    posthog.capture('quickstart action clicked', { action, ...(productKey ? { product_key: productKey } : {}) })
}

function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }): JSX.Element {
    return (
        <div className="mb-4">
            <h2 className="text-lg font-semibold mb-0">{title}</h2>
            {subtitle && <p className="text-secondary mb-0 mt-1">{subtitle}</p>}
        </div>
    )
}

function WaitingForEventsIndicator(): JSX.Element {
    return (
        <div className="flex items-center gap-2 px-2 py-1 border border-accent rounded-sm self-start">
            <div className="relative flex items-center justify-center">
                <div className="absolute w-3 h-3 border-2 border-accent rounded-full animate-ping" />
                <div className="w-2 h-2 bg-accent rounded-full" />
            </div>
            <span className="text-sm text-accent whitespace-nowrap">Waiting for your first event…</span>
        </div>
    )
}

function GetDataFlowingSection(): JSX.Element {
    const installationComplete = useInstallationComplete('ingested_event')
    const { wizardCommand, isCloudOrDev } = useWizardCommand()
    const { showInviteModal } = useActions(inviteLogic)

    if (installationComplete) {
        return (
            <div className="flex items-center gap-1.5 text-sm text-secondary">
                <IconCheckCircle className="text-success text-base shrink-0" />
                <span>Events are flowing.</span>
                <Link
                    to={urls.activity(ActivityTab.ExploreEvents)}
                    onClick={() => captureQuickstartAction('view_events')}
                    data-attr="quickstart-view-events"
                >
                    View events
                </Link>
            </div>
        )
    }

    return (
        <LemonCard hoverEffect={false}>
            <div className="flex flex-wrap items-start justify-between gap-2 mb-4">
                <SectionHeader
                    title="Get your data flowing"
                    subtitle="PostHog needs events from your app. One install powers every product below."
                />
                <WaitingForEventsIndicator />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {isCloudOrDev && (
                    <div className="flex flex-col gap-2">
                        <h3 className="text-sm font-semibold mb-0">Fastest: the AI setup wizard</h3>
                        <p className="text-secondary text-sm mb-0">
                            Run this in your project root. It detects your framework, installs the SDK, and configures
                            event capture for you.
                        </p>
                        <CodeSnippet language={Language.Bash}>{wizardCommand}</CodeSnippet>
                    </div>
                )}
                <div className="flex flex-col gap-2">
                    <h3 className="text-sm font-semibold mb-0">Other ways to get set up</h3>
                    <LemonButton
                        type="secondary"
                        fullWidth
                        to={urls.onboarding({
                            productKey: ProductKey.PRODUCT_ANALYTICS,
                            stepKey: OnboardingStepKey.INSTALL,
                        })}
                        onClick={() => captureQuickstartAction('install_manually')}
                        data-attr="quickstart-install-manually"
                    >
                        Follow the install guide for your framework
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        fullWidth
                        onClick={() => {
                            captureQuickstartAction('invite_teammate')
                            showInviteModal()
                        }}
                        data-attr="quickstart-invite-teammate"
                    >
                        Invite a developer to install it for you
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        fullWidth
                        to={urls.sources()}
                        onClick={() => captureQuickstartAction('connect_source')}
                        data-attr="quickstart-connect-source"
                    >
                        No app? Connect a data source instead
                    </LemonButton>
                </div>
            </div>
        </LemonCard>
    )
}

function ProductStatusTag({ status }: { status: QuickstartProduct['status'] }): JSX.Element {
    if (status === 'active') {
        return <LemonTag type="success">Active</LemonTag>
    }
    if (status === 'ready') {
        return <LemonTag type="completion">1-click enable</LemonTag>
    }
    return <LemonTag type="muted">Needs setup</LemonTag>
}

function ProductCard({ product }: { product: QuickstartProduct }): JSX.Element {
    const { enablingProducts } = useValues(quickstartLogic)
    const { enableProduct } = useActions(quickstartLogic)

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-2 p-4">
            <div className="flex items-start justify-between gap-2">
                <span className="text-2xl leading-none">
                    {getProductIcon(product.icon, { iconColor: product.iconColor })}
                </span>
                <ProductStatusTag status={product.status} />
            </div>
            <div>
                <h3 className="font-semibold text-base mb-0">{product.name}</h3>
                <div className="text-xs text-tertiary">Best for {product.bestFor}</div>
            </div>
            <p className="text-secondary text-sm mb-0 flex-1">{product.description}</p>
            <div className="flex items-center gap-2 mt-1">
                {product.status === 'active' ? (
                    <LemonButton
                        type="primary"
                        size="small"
                        to={product.url}
                        onClick={() => captureQuickstartAction('open_product', product.key)}
                        data-attr={`quickstart-open-${product.key}`}
                    >
                        Open
                    </LemonButton>
                ) : product.status === 'ready' ? (
                    <LemonButton
                        type="primary"
                        size="small"
                        loading={!!enablingProducts[product.key]}
                        onClick={() => enableProduct(product.key)}
                        data-attr={`quickstart-enable-${product.key}`}
                    >
                        Enable
                    </LemonButton>
                ) : (
                    <LemonButton
                        type="primary"
                        size="small"
                        to={product.setupUrl}
                        onClick={() => captureQuickstartAction('set_up_product', product.key)}
                        data-attr={`quickstart-setup-${product.key}`}
                    >
                        Set up
                    </LemonButton>
                )}
                {product.docsUrl && (
                    <LemonButton
                        size="small"
                        to={product.docsUrl}
                        targetBlank
                        onClick={() => captureQuickstartAction('open_docs', product.key)}
                        data-attr={`quickstart-docs-${product.key}`}
                    >
                        Docs
                    </LemonButton>
                )}
            </div>
        </LemonCard>
    )
}

function LearnCard({
    icon,
    title,
    description,
    buttonLabel,
    to,
    targetBlank,
    action,
}: {
    icon: JSX.Element
    title: string
    description: string
    buttonLabel: string
    to: string
    targetBlank?: boolean
    action: string
}): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-2 p-4">
            <span className="text-xl text-secondary">{icon}</span>
            <h3 className="font-semibold text-base mb-0">{title}</h3>
            <p className="text-secondary text-sm mb-0 flex-1">{description}</p>
            <div>
                <LemonButton
                    type="secondary"
                    size="small"
                    to={to}
                    targetBlank={targetBlank}
                    onClick={() => captureQuickstartAction(action)}
                    data-attr={`quickstart-learn-${action}`}
                >
                    {buttonLabel}
                </LemonButton>
            </div>
        </LemonCard>
    )
}

function PublicationCard({ publication }: { publication: QuickstartPublication }): JSX.Element {
    return (
        <LemonCard hoverEffect className="p-0 overflow-hidden">
            <Link
                to={publication.url}
                target="_blank"
                className="flex flex-col h-full text-primary hover:text-primary"
                onClick={() =>
                    posthog.capture('quickstart action clicked', {
                        action: 'open_publication',
                        url: publication.url,
                    })
                }
                data-attr="quickstart-publication-card"
            >
                {publication.imageUrl && (
                    <img
                        src={publication.imageUrl}
                        alt=""
                        className="w-full aspect-video object-cover bg-surface-secondary"
                        loading="lazy"
                        onError={(e) => {
                            e.currentTarget.style.display = 'none'
                        }}
                    />
                )}
                <div className="flex flex-col gap-1 p-3 flex-1">
                    <h3 className="font-semibold text-sm mb-0 line-clamp-2">{publication.title}</h3>
                    <p className="text-secondary text-xs mb-0 line-clamp-2 flex-1">{publication.description}</p>
                    <div className="text-xs text-tertiary mt-1">
                        {publication.author ? `${publication.author} · ` : ''}
                        {dayjs(publication.publishedAt).fromNow()}
                    </div>
                </div>
            </Link>
        </LemonCard>
    )
}

function LoadMoreSentinel({ onVisible }: { onVisible: () => void }): JSX.Element {
    const ref = useRef<HTMLDivElement | null>(null)

    useEffect(() => {
        const element = ref.current
        if (!element) {
            return
        }
        const observer = new IntersectionObserver(
            (entries) => {
                if (entries.some((entry) => entry.isIntersecting)) {
                    onVisible()
                }
            },
            { rootMargin: '400px' }
        )
        observer.observe(element)
        return () => observer.disconnect()
    }, [onVisible])

    return <div ref={ref} className="h-px" />
}

function PublicationsSection(): JSX.Element | null {
    const { publications, publicationsLoading, hasMorePublications } = useValues(quickstartLogic)
    const { loadMorePublications } = useActions(quickstartLogic)

    if (!publicationsLoading && publications.length === 0) {
        return null
    }

    return (
        <section>
            <div className="flex items-start justify-between gap-2">
                <SectionHeader title="Fresh from PostHog" subtitle="What we've been shipping and writing about." />
                <LemonButton
                    size="small"
                    to="https://posthog.com/blog"
                    targetBlank
                    onClick={() => captureQuickstartAction('open_blog')}
                    data-attr="quickstart-publications-view-all"
                >
                    View all
                </LemonButton>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
                {publications.map((publication) => (
                    <PublicationCard key={publication.url} publication={publication} />
                ))}
                {publicationsLoading &&
                    Array.from({ length: publications.length === 0 ? 8 : 4 }, (_, index) => (
                        <LemonCard key={`skeleton-${index}`} hoverEffect={false} className="flex flex-col gap-2 p-3">
                            <LemonSkeleton className="w-full h-24 rounded" />
                            <LemonSkeleton className="w-3/4 h-4" />
                            <LemonSkeleton className="w-full h-3" />
                        </LemonCard>
                    ))}
            </div>
            {!publicationsLoading && hasMorePublications && <LoadMoreSentinel onVisible={loadMorePublications} />}
            {!hasMorePublications && publications.length > 0 && (
                <div className="flex items-center justify-center gap-2 py-6 text-sm text-secondary">
                    <span>That's everything recent.</span>
                    <Link
                        to="https://posthog.com/blog"
                        target="_blank"
                        onClick={() => captureQuickstartAction('open_blog')}
                        data-attr="quickstart-publications-feed-end"
                    >
                        Keep reading on the blog
                    </Link>
                </div>
            )}
        </section>
    )
}

export function Quickstart(): JSX.Element {
    const { user } = useValues(userLogic)
    const { featuredProducts, moreProducts } = useValues(quickstartLogic)

    return (
        <div className="flex flex-col gap-8 py-4">
            <div className="flex flex-col gap-3">
                <Logomark size="xl" className="self-start" />
                <div>
                    <h1 className="text-2xl font-bold mb-1">
                        Welcome to PostHog{user?.first_name ? `, ${user.first_name}` : ''} 👋
                    </h1>
                    <p className="text-secondary mb-0 max-w-200">
                        Every product here runs on the same events. Get data flowing once, then turn things on as you
                        need them. No extra installs.
                    </p>
                </div>
            </div>

            <GetDataFlowingSection />

            <section>
                <SectionHeader
                    title="Turn on your products"
                    subtitle="What most teams start with. Active products are already collecting or ready to use."
                />
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                    {featuredProducts.map((product) => (
                        <ProductCard key={product.key} product={product} />
                    ))}
                </div>
            </section>

            <section>
                <SectionHeader
                    title="Explore the rest of the platform"
                    subtitle="More tools that work on the same data, whenever you're ready for them."
                />
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
                    {moreProducts.map((product) => (
                        <ProductCard key={product.key} product={product} />
                    ))}
                </div>
            </section>

            <section>
                <SectionHeader title="Learn the ropes" />
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <LearnCard
                        icon={<IconSparkles />}
                        title="Ask Max anything"
                        description={
                            'Max is PostHog\'s AI analyst. Once events are flowing, ask questions in plain English, like "What are my most visited pages this week?"'
                        }
                        buttonLabel="Ask Max"
                        to={urls.projectHomepage()}
                        action="ask_max"
                    />
                    <LearnCard
                        icon={<IconBook />}
                        title="Read the docs"
                        description="Guides for every product, SDK, and framework, from first install to advanced setups."
                        buttonLabel="Open docs"
                        to="https://posthog.com/docs"
                        targetBlank
                        action="open_docs_home"
                    />
                    <LearnCard
                        icon={<IconGraduationCap />}
                        title="Follow a tutorial"
                        description="Step-by-step walkthroughs of real setups: funnels, feature flags, A/B tests, and more."
                        buttonLabel="Browse tutorials"
                        to="https://posthog.com/tutorials"
                        targetBlank
                        action="open_tutorials"
                    />
                </div>
            </section>

            <PublicationsSection />
        </div>
    )
}

export default Quickstart
