import { decode } from 'he'
import { useActions, useValues } from 'kea'

import { LemonBanner, LemonDivider, LemonSkeleton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconKey } from 'lib/lemon-ui/icons'
import type { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { OAuthApplicationLogicProps, oauthApplicationLogic } from './oauthApplicationLogic'
import { OAuthApplicationRegistration } from './OAuthApplicationRegistration'
import { OAuthApplicationReview } from './OAuthApplicationReview'
import { OAuthApplicationVerification } from './OAuthApplicationVerification'
import { QuillOAuthApplicationPage } from './QuillOAuthApplicationPage'

export const scene: SceneExport<OAuthApplicationLogicProps> = {
    component: OAuthApplicationScene,
    logic: oauthApplicationLogic,
    paramsToProps: ({ params }) => ({ id: params.id }),
}

export function OAuthApplicationScene(): JSX.Element {
    const { application, applicationLoading, applicationLoadFailed, applicationNotFound } =
        useValues(oauthApplicationLogic)
    const { loadApplication } = useActions(oauthApplicationLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return <QuillOAuthApplicationPage />
    }
    if (applicationNotFound) {
        return <NotFound object="OAuth application" />
    }

    return (
        <SceneContent className="pb-8">
            <SceneTitleSection
                name={application ? decode(application.name ?? '') : null}
                isLoading={!application}
                resourceType={{ type: 'oauth_application', forceIcon: <IconKey /> }}
            />
            {applicationLoadFailed ? (
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: loadApplication, loading: applicationLoading }}
                >
                    Couldn't load this application. Try again, and if it keeps happening contact support.
                </LemonBanner>
            ) : !application ? (
                <div className="max-w-200 flex flex-col gap-3">
                    <LemonSkeleton className="h-8 w-1/3" />
                    <LemonSkeleton className="h-24" />
                    <LemonSkeleton className="h-48" />
                </div>
            ) : (
                <div className="max-w-200 flex flex-col gap-6">
                    {application.provisioning_status !== 'not_a_partner' && (
                        <>
                            <OAuthApplicationReview app={application} />
                            <LemonDivider />
                        </>
                    )}
                    <OAuthApplicationVerification app={application} />
                    <LemonDivider />
                    <OAuthApplicationRegistration
                        clientId={application.client_id ?? ''}
                        registration={application.registration}
                    />
                </div>
            )}
        </SceneContent>
    )
}
