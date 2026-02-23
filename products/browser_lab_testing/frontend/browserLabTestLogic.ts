import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { browserLabTestLogicType } from './browserLabTestLogicType'
import type { BrowserLabTestType } from './types'

export interface BrowserLabTestLogicProps {
    id: string
}

const NEW_BROWSER_LAB_TEST: Partial<BrowserLabTestType> = {
    id: 'new',
    name: '',
    url: '',
    steps: [],
    secrets: {},
}

export const browserLabTestLogic = kea<browserLabTestLogicType>([
    path(['products', 'browser_lab_testing', 'frontend', 'browserLabTestLogic']),
    props({} as BrowserLabTestLogicProps),
    key(({ id }) => id),
    actions({
        setBrowserLabTestMissing: true,
    }),
    loaders(({ props, actions }) => ({
        browserLabTest: {
            loadBrowserLabTest: async (): Promise<BrowserLabTestType> => {
                if (props.id && props.id !== 'new') {
                    try {
                        return await api.get(`api/environments/@current/browser_lab_tests/${props.id}/`)
                    } catch (error) {
                        actions.setBrowserLabTestMissing()
                        throw error
                    }
                }
                return NEW_BROWSER_LAB_TEST as BrowserLabTestType
            },
        },
    })),
    forms(({ props }) => ({
        browserLabTest: {
            defaults: { ...NEW_BROWSER_LAB_TEST } as BrowserLabTestType,
            errors: (payload: Partial<BrowserLabTestType>) => ({
                name: !payload?.name ? 'Name is required' : undefined,
                url: !payload?.url ? 'URL is required' : undefined,
            }),
            submit: async (payload: BrowserLabTestType) => {
                const data = {
                    name: payload.name,
                    url: payload.url,
                    steps: payload.steps,
                    secrets: payload.secrets,
                }
                if (props.id === 'new') {
                    const result = await api.create('api/environments/@current/browser_lab_tests/', data)
                    router.actions.replace(urls.browserLabTest(result.id))
                    return result
                }
                const result = await api.update(`api/environments/@current/browser_lab_tests/${props.id}/`, data)
                return result
            },
        },
    })),
    reducers({
        browserLabTestMissing: [false, { setBrowserLabTestMissing: () => true }],
    }),
    selectors({
        breadcrumbs: [
            (s) => [s.browserLabTest],
            (browserLabTest: BrowserLabTestType): Breadcrumb[] => [
                {
                    key: 'BrowserLabTests',
                    name: 'Browser lab tests',
                    path: urls.browserLabTests(),
                },
                {
                    key: ['BrowserLabTest', browserLabTest?.id || 'new'],
                    name: browserLabTest?.name || 'New test',
                },
            ],
        ],
    }),
    listeners(() => ({
        submitBrowserLabTestSuccess: () => {
            lemonToast.success('Test saved')
        },
        submitBrowserLabTestFailure: ({ error }: { error: Error }) => {
            lemonToast.error(`Failed to save: ${error.message}`)
        },
    })),
    afterMount(({ props, actions }) => {
        if (props.id !== 'new') {
            actions.loadBrowserLabTest()
        }
    }),
])
