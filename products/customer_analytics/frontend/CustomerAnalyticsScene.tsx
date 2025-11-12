import { QueryCard } from 'lib/components/Cards/InsightCard/QueryCard'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { customerAnalyticsSceneLogic } from './customerAnalyticsSceneLogic'
import {
    CUSTOMER_ANALYTICS_ACTIVE_USERS_INSIGHTS,
    CUSTOMER_ANALYTICS_ENGAGEMENT_AND_CONVERSION_INSIGHTS,
    CUSTOMER_ANALYTICS_SESSION_INSIGHTS,
    CUSTOMER_ANALYTICS_SIGNUP_AND_SUBS_INSIGHTS,
} from './insightDefinitions'

export const scene: SceneExport = {
    component: CustomerAnalyticsScene,
    logic: customerAnalyticsSceneLogic,
}

export function CustomerAnalyticsScene(): JSX.Element {
    return (
        <SceneContent>
            <Header />
            <Insights />
        </SceneContent>
    )
}

const Header = (): JSX.Element => {
    return (
        <SceneTitleSection
            name={sceneConfigurations[Scene.CustomerAnalytics].name}
            description={sceneConfigurations[Scene.CustomerAnalytics].description}
            resourceType={{
                type: sceneConfigurations[Scene.CustomerAnalytics].iconType || 'default_icon_type',
            }}
        />
    )
}

function Insights(): JSX.Element {
    return (
        <div className="space-y-2">
            <ActiveUsersInsights />
            <EngagementAndConversionInsights />
            <SessionInsights />
            <SignupInsights />
        </div>
    )
}

function ActiveUsersInsights(): JSX.Element {
    return (
        <div className="space-y-2">
            <div>Active Users</div>
            <div className="grid grid-cols-[3fr_1fr] gap-2">
                {CUSTOMER_ANALYTICS_ACTIVE_USERS_INSIGHTS.map((insight, index) => {
                    return (
                        <QueryCard
                            key={index}
                            title={insight.name}
                            description={insight.description}
                            query={insight.query}
                            context={{ refresh: 'force_blocking' }}
                            className={insight?.className || ''}
                        />
                    )
                })}
            </div>
        </div>
    )
}

function EngagementAndConversionInsights(): JSX.Element {
    return (
        <div className="space-y-2">
            <div>Engagement and conversion</div>
            <div className="grid grid-cols-2 gap-2">
                {CUSTOMER_ANALYTICS_ENGAGEMENT_AND_CONVERSION_INSIGHTS.map((insight, index) => {
                    return (
                        <QueryCard
                            key={index}
                            title={insight.name}
                            description={insight.description}
                            query={insight.query}
                            context={{ refresh: 'force_blocking' }}
                            className={insight?.className || ''}
                        />
                    )
                })}
            </div>
        </div>
    )
}

function SessionInsights(): JSX.Element {
    return (
        <div className="space-y-2">
            <div>Sessions</div>
            <div className="grid grid-cols-3 gap-2">
                {CUSTOMER_ANALYTICS_SESSION_INSIGHTS.map((insight, index) => {
                    return (
                        <QueryCard
                            key={index}
                            title={insight.name}
                            description={insight.description}
                            query={insight.query}
                            context={{ refresh: 'force_blocking' }}
                            className={insight?.className || ''}
                        />
                    )
                })}
            </div>
        </div>
    )
}

function SignupInsights(): JSX.Element {
    return (
        <div className="space-y-2">
            <div>Signups and conversion</div>
            <div className="grid grid-cols-2 gap-2">
                <div className="grid grid-cols-2 gap-2">
                    {CUSTOMER_ANALYTICS_SIGNUP_AND_SUBS_INSIGHTS.slice(0, 2).map((insight, index) => {
                        return (
                            <QueryCard
                                key={index}
                                title={insight.name}
                                description={insight.description}
                                query={insight.query}
                                context={{ refresh: 'force_blocking' }}
                                className={insight?.className || ''}
                            />
                        )
                    })}
                </div>
                <QueryCard
                    title={CUSTOMER_ANALYTICS_SIGNUP_AND_SUBS_INSIGHTS[2].name}
                    description={CUSTOMER_ANALYTICS_SIGNUP_AND_SUBS_INSIGHTS[2].description}
                    query={CUSTOMER_ANALYTICS_SIGNUP_AND_SUBS_INSIGHTS[2].query}
                    context={{ refresh: 'force_blocking' }}
                    className={CUSTOMER_ANALYTICS_SIGNUP_AND_SUBS_INSIGHTS[2]?.className || ''}
                />
            </div>
            <div className="grid grid-cols-3 gap-2">
                {CUSTOMER_ANALYTICS_SIGNUP_AND_SUBS_INSIGHTS.slice(3, 6).map((insight, index) => {
                    return (
                        <QueryCard
                            key={index}
                            title={insight.name}
                            description={insight.description}
                            query={insight.query}
                            context={{ refresh: 'force_blocking' }}
                            className={insight?.className || ''}
                        />
                    )
                })}
            </div>
            <div className="grid grid-cols-2 gap-2">
                {CUSTOMER_ANALYTICS_SIGNUP_AND_SUBS_INSIGHTS.slice(6).map((insight, index) => {
                    return (
                        <QueryCard
                            key={index}
                            title={insight.name}
                            description={insight.description}
                            query={insight.query}
                            context={{ refresh: 'force_blocking' }}
                            className={insight?.className || ''}
                        />
                    )
                })}
            </div>
        </div>
    )
}
