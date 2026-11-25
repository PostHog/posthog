import { decode } from 'he'
import { useActions, useValues } from 'kea'

import { Button, Item, ItemActions, ItemContent, ItemDescription, Separator, Skeleton } from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { IconKey } from 'lib/lemon-ui/icons'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { oauthApplicationLogic } from './oauthApplicationLogic'
import { QuillOAuthApplicationRegistration } from './QuillOAuthApplicationRegistration'
import { QuillOAuthApplicationReview } from './QuillOAuthApplicationReview'
import { QuillOAuthApplicationVerification } from './QuillOAuthApplicationVerification'

export function QuillOAuthApplicationPage(): JSX.Element {
    const { application, applicationLoading, applicationLoadFailed, applicationNotFound } =
        useValues(oauthApplicationLogic)
    const { loadApplication } = useActions(oauthApplicationLogic)

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
                <Item tone="destructive" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            Couldn't load this application. Try again, and if it keeps happening contact support.
                        </ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <Button variant="outline" onClick={loadApplication} loading={applicationLoading}>
                            Try again
                        </Button>
                    </ItemActions>
                </Item>
            ) : !application ? (
                <div className="max-w-200 flex flex-col gap-3">
                    <Skeleton className="h-8 w-1/3" />
                    <Skeleton className="h-24" />
                    <Skeleton className="h-48" />
                </div>
            ) : (
                <div className="max-w-200 flex flex-col gap-6">
                    {application.provisioning_status !== 'not_a_partner' && (
                        <>
                            <QuillOAuthApplicationReview app={application} />
                            <Separator />
                        </>
                    )}
                    <QuillOAuthApplicationVerification app={application} />
                    <Separator />
                    <QuillOAuthApplicationRegistration
                        clientId={application.client_id ?? ''}
                        registration={application.registration}
                    />
                </div>
            )}
        </SceneContent>
    )
}
