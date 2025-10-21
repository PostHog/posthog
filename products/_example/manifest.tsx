import { FEATURE_FLAGS } from 'lib/constants'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Example',
    scenes: {
        [Scene.ExampleApp]: {
            import: () => import('./frontend/ExampleAppScene'),
            projectBased: true,
            name: 'Example app',
            layout: 'app-container',
            iconType: 'example_icon_type',
            // Descriptions are used for the scene title section, and for the nav bar app's tooltip.
            description:
                'We define our description here to describe what this scene is about. This is a list view of example apps.',
        },
        [Scene.ExampleAppDetail]: {
            import: () => import('./frontend/ExampleAppDetailScene'),
            projectBased: true,
            name: 'Example app detail',
            layout: 'app-container',
            iconType: 'example_icon_type',
            // description: 'Detail view descriptions are shouldn\'t be used, as detail descriptions are userland.',
        },
    },
    routes: {
        '/example-app': [Scene.ExampleApp, 'exampleApp'],
        '/example-app/:id': [Scene.ExampleAppDetail, 'exampleAppDetail'],
    },
    urls: {
        exampleApp: (): string => '/example-app',
        exampleAppDetail: (id: string): string => `/example-app/${id}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Example app',
            category: 'Unreleased',
            iconType: 'example_icon_type',
            iconColor: ['var(--color-orange-900)', 'var(--color-orange-500)'],
            href: urls.exampleApp(),
            flag: FEATURE_FLAGS.EXAMPLE_APP_LIST_VIEW,
            tags: ['alpha'],
            sceneKey: Scene.ExampleApp,
        },
    ],
}
