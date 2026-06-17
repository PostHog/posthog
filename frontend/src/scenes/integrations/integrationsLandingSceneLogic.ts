import { actions, kea, path, reducers, selectors } from 'kea'
import { urlToAction } from 'kea-router'

import { INTEGRATIONS_BY_SLUG } from './definitions'
import { Integration } from './integrationDefinition'
import type { integrationsLandingSceneLogicType } from './integrationsLandingSceneLogicType'

export const integrationsLandingSceneLogic = kea<integrationsLandingSceneLogicType>([
    path(['scenes', 'integrations', 'integrationsLandingSceneLogic']),
    actions({
        setSlug: (slug: string | null) => ({ slug }),
    }),
    reducers({
        slug: [
            null as string | null,
            {
                setSlug: (_, { slug }) => slug,
            },
        ],
    }),
    selectors({
        integration: [
            (s) => [s.slug],
            (slug): Integration | null => (slug ? (INTEGRATIONS_BY_SLUG[slug] ?? null) : null),
        ],
    }),
    urlToAction(({ actions }) => ({
        '/integrations/:slug': ({ slug }) => {
            actions.setSlug(slug ?? null)
        },
    })),
])
