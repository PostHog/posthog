import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useRef } from 'react'

import {
    IconApps,
    IconBook,
    IconCheckCircle,
    IconGear,
    IconGraduationCap,
    IconPeople,
    IconSparkles,
} from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LiveUserCount } from 'lib/components/LiveUserCount'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { dayjs } from 'lib/dayjs'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'
import { useInstallationComplete } from 'scenes/onboarding/legacy/sdks/hooks/useInstallationComplete'
import { useWizardCommand } from 'scenes/onboarding/shared/SetupWizardBanner'
import { getProductIcon } from 'scenes/onboarding/shared/utils'
import { organizationLogic } from 'scenes/organizationLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { ProductKey } from '~/queries/schema/schema-general'
import { ActivityTab, OnboardingStepKey } from '~/types'

import {
    PublicationFeedKey,
    QUICKSTART_BLOG_URL,
    QUICKSTART_NEWSLETTER_URL,
    QuickstartPublication,
} from './publications'
import { QuickstartProduct, quickstartLogic } from './quickstartLogic'

export const scene: SceneExport = {
    component: Quickstart,
    logic: quickstartLogic,
}

const HERO_IMAGE_URL =
    'https://res.cloudinary.com/dmukukwp6/image/upload/w_800,c_limit,q_auto,f_auto/logs_hogs_5d5e98d9e6.png'

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

function EventsWaitingStatus(): JSX.Element {
    return (
        <div className="flex items-center gap-2 text-sm text-secondary">
            <div className="relative flex items-center justify-center shrink-0">
                <div className="absolute w-3 h-3 border-2 border-accent rounded-full animate-ping" />
                <div className="w-2 h-2 bg-accent rounded-full" />
            </div>
            <span>Waiting for your first event…</span>
        </div>
    )
}

function HeaderStat({ icon, children }: { icon: JSX.Element; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex items-center gap-1.5 text-sm text-secondary">
            <span className="text-base leading-none">{icon}</span>
            {children}
        </div>
    )
}

function EventsFlowingStatus(): JSX.Element {
    return (
        <div className="flex items-center gap-1.5 text-sm text-secondary">
            <IconCheckCircle className="text-success text-base shrink-0" />
            <span>Receiving events</span>
            <Link
                to={urls.activity(ActivityTab.LiveEvents)}
                onClick={() => captureQuickstartAction('view_events')}
                data-attr="quickstart-view-events"
            >
                View live
            </Link>
        </div>
    )
}

function InstallHeroCard(): JSX.Element {
    const { wizardCommand, isCloudOrDev } = useWizardCommand()
    const { showInviteModal } = useActions(inviteLogic)

    return (
        <LemonCard hoverEffect={false} className="rounded-lg border-transparent shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-2 mb-4">
                <SectionHeader
                    title="Get your data flowing"
                    subtitle="PostHog needs events from your app. One install powers every tool below."
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
        <LemonCard hoverEffect={false} className="flex flex-col gap-2 p-4 rounded-lg border-transparent shadow-sm">
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
        <LemonCard hoverEffect={false} className="flex flex-col gap-2 p-4 rounded-lg border-transparent shadow-sm">
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

function PublicationCard({
    publication,
    feed,
}: {
    publication: QuickstartPublication
    feed: PublicationFeedKey
}): JSX.Element {
    return (
        <LemonCard hoverEffect className="p-0 overflow-hidden h-full rounded-lg border-transparent shadow-sm">
            <Link
                to={publication.url}
                target="_blank"
                className="flex flex-col h-full text-primary hover:text-primary"
                onClick={() =>
                    posthog.capture('quickstart action clicked', {
                        action: 'open_publication',
                        feed,
                        url: publication.url,
                    })
                }
                data-attr={`quickstart-publication-card-${feed}`}
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

function PublicationSkeletonCard(): JSX.Element {
    return (
        <LemonCard
            hoverEffect={false}
            className="flex flex-col gap-2 p-3 h-full rounded-lg border-transparent shadow-sm"
        >
            <LemonSkeleton className="w-full h-24 rounded" />
            <LemonSkeleton className="w-3/4 h-4" />
            <LemonSkeleton className="w-full h-3" />
        </LemonCard>
    )
}

function PublicationRail({
    feed,
    title,
    viewAllUrl,
    viewAllLabel,
    endLabel,
    publications,
    loading,
    hasMore,
    onLoadMore,
}: {
    feed: PublicationFeedKey
    title: string
    viewAllUrl: string
    viewAllLabel: string
    endLabel: string
    publications: QuickstartPublication[]
    loading: boolean
    hasMore: boolean
    onLoadMore: () => void
}): JSX.Element | null {
    if (!loading && publications.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-semibold mb-0">{title}</h3>
                <Link
                    to={viewAllUrl}
                    target="_blank"
                    className="text-sm"
                    onClick={() => captureQuickstartAction(`view_all_${feed}`)}
                    data-attr={`quickstart-publications-view-all-${feed}`}
                >
                    {viewAllLabel}
                </Link>
            </div>
            <ScrollableShadows
                direction="horizontal"
                innerClassName="snap-x"
                contentClassName="flex w-max min-w-full items-stretch gap-4 pb-1"
                styledScrollbars
            >
                {publications.map((publication) => (
                    <div key={publication.url} className="w-72 shrink-0 snap-start">
                        <PublicationCard publication={publication} feed={feed} />
                    </div>
                ))}
                {loading &&
                    Array.from({ length: publications.length === 0 ? 4 : 2 }, (_, index) => (
                        <div key={`skeleton-${index}`} className="w-72 shrink-0">
                            <PublicationSkeletonCard />
                        </div>
                    ))}
                {!loading && hasMore && <LoadMoreSentinel onVisible={onLoadMore} />}
                {!loading && !hasMore && publications.length > 0 && (
                    <div className="w-56 shrink-0 snap-start flex items-center justify-center rounded border border-dashed p-4 text-center">
                        <Link
                            to={viewAllUrl}
                            target="_blank"
                            className="text-sm"
                            onClick={() => captureQuickstartAction(`view_all_${feed}`)}
                            data-attr={`quickstart-publications-feed-end-${feed}`}
                        >
                            {endLabel}
                        </Link>
                    </div>
                )}
            </ScrollableShadows>
        </div>
    )
}

function PublicationsSection(): JSX.Element | null {
    const {
        blogPublications,
        blogPublicationsLoading,
        newsletterPublications,
        newsletterPublicationsLoading,
        publicationsHasMore,
    } = useValues(quickstartLogic)
    const { loadMoreBlogPublications, loadMoreNewsletterPublications } = useActions(quickstartLogic)

    const nothingToShow =
        !blogPublicationsLoading &&
        blogPublications.length === 0 &&
        !newsletterPublicationsLoading &&
        newsletterPublications.length === 0
    if (nothingToShow) {
        return null
    }

    return (
        <section className="flex flex-col gap-4">
            <SectionHeader title="Fresh from PostHog" subtitle="What we've been shipping and writing about." />
            <PublicationRail
                feed="blog"
                title="From the blog"
                viewAllUrl={QUICKSTART_BLOG_URL}
                viewAllLabel="View all posts"
                endLabel="Keep reading on the blog"
                publications={blogPublications}
                loading={blogPublicationsLoading}
                hasMore={publicationsHasMore.blog}
                onLoadMore={loadMoreBlogPublications}
            />
            <PublicationRail
                feed="newsletter"
                title="build mode, our newsletter"
                viewAllUrl={QUICKSTART_NEWSLETTER_URL}
                viewAllLabel="Read & subscribe"
                endLabel="More issues + subscribe"
                publications={newsletterPublications}
                loading={newsletterPublicationsLoading}
                hasMore={publicationsHasMore.newsletter}
                onLoadMore={loadMoreNewsletterPublications}
            />
        </section>
    )
}

export function Quickstart(): JSX.Element {
    const { user } = useValues(userLogic)
    const { featuredProducts, moreProducts, activeProductCount, totalProductCount } = useValues(quickstartLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { showInviteModal } = useActions(inviteLogic)
    const { showConfigureHomeModal } = useActions(navigationLogic)
    const installationComplete = useInstallationComplete('ingested_event')

    return (
        <div className="flex flex-col gap-8 py-4">
            <section className="rounded-lg border bg-surface-secondary flex items-stretch gap-6 overflow-hidden">
                <img src={HERO_IMAGE_URL} alt="" className="w-56 lg:w-72 shrink-0 object-cover hidden md:block" />
                <div className="flex flex-col justify-center gap-3 min-w-0 flex-1 p-4 md:p-6 md:pl-0">
                    <div>
                        <h1 className="text-3xl font-bold mb-1">
                            Welcome to PostHog{user?.first_name ? `, ${user.first_name}` : ''} 👋
                        </h1>
                        <p className="text-secondary mb-0 max-w-200">
                            Every tool here runs on the same events. Get data flowing once, then turn things on as you
                            need them. No extra installs.
                        </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                        {installationComplete ? <EventsFlowingStatus /> : <EventsWaitingStatus />}
                        <Link
                            to={urls.webAnalyticsLive()}
                            onClick={() => captureQuickstartAction('view_live_users')}
                            data-attr="quickstart-live-users"
                        >
                            <LiveUserCount />
                        </Link>
                        <HeaderStat icon={<IconApps />}>
                            {activeProductCount} of {totalProductCount} tools active
                        </HeaderStat>
                        {currentOrganization?.member_count ? (
                            <HeaderStat icon={<IconPeople />}>
                                {currentOrganization.member_count === 1
                                    ? '1 teammate'
                                    : `${currentOrganization.member_count} teammates`}
                            </HeaderStat>
                        ) : null}
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        <LemonButton
                            type="primary"
                            size="small"
                            icon={<IconSparkles />}
                            to={urls.projectHomepage()}
                            onClick={() => captureQuickstartAction('ask_posthog_ai_header')}
                            data-attr="quickstart-header-ask-posthog-ai"
                        >
                            Ask PostHog AI
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconPeople />}
                            onClick={() => {
                                captureQuickstartAction('invite_teammate_header')
                                showInviteModal()
                            }}
                            data-attr="quickstart-header-invite"
                        >
                            Invite teammates
                        </LemonButton>
                        <LemonButton
                            size="small"
                            icon={<IconGear />}
                            tooltip="Choose what your Home button opens"
                            onClick={() => {
                                captureQuickstartAction('configure_homepage')
                                showConfigureHomeModal()
                            }}
                            data-attr="quickstart-header-configure-home"
                        >
                            Change homepage
                        </LemonButton>
                    </div>
                </div>
            </section>

            {!installationComplete && <InstallHeroCard />}

            <section>
                <SectionHeader
                    title="Turn on your tools"
                    subtitle="What most teams start with. Active tools are already collecting or ready to use."
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
                        title="Ask PostHog AI anything"
                        description='Once events are flowing, ask PostHog AI questions in plain English, like "What are my most visited pages this week?"'
                        buttonLabel="Ask PostHog AI"
                        to={urls.projectHomepage()}
                        action="ask_posthog_ai"
                    />
                    <LearnCard
                        icon={<IconBook />}
                        title="Read the docs"
                        description="Guides for every tool, SDK, and framework, from first install to advanced setups."
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
