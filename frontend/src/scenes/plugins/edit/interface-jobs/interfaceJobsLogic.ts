import type { FormInstance } from 'antd/lib/form/hooks/useForm.d'
import { actions, events, kea, key, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { validateJson } from 'lib/utils'

import { JobSpec } from '~/types'

import type { interfaceJobsLogicType } from './interfaceJobsLogicType'

export interface InterfaceJobsProps {
    jobName: string
    jobSpec: JobSpec
    pluginConfigId: number
    pluginId: number
    onSubmit?: () => void
}

export const interfaceJobsLogic = kea<interfaceJobsLogicType>([
    path(['scenes', 'plugins', 'edit', 'interface-jobs', 'interfaceJobsLogic']),
    props({} as InterfaceJobsProps),
    key((props) => {
        return `${props.pluginId}_${props.jobName}`
    }),
    actions({
        setIsJobModalOpen: (isOpen: boolean) => ({ isOpen }),
        setRunJobAvailable: (isAvailable: boolean) => ({ isAvailable }),
        runJob: (form: FormInstance<any>) => ({ form }),
        playButtonOnClick: (jobHasEmptyPayload: boolean) => ({ jobHasEmptyPayload }),
        setRunJobAvailableTimeout: (timeout: number) => ({ timeout }),
    }),
    reducers({
        isJobModalOpen: [
            false,
            {
                setIsJobModalOpen: (_, { isOpen }) => isOpen,
            },
        ],
        runJobAvailable: [
            true,
            {
                setRunJobAvailable: (_, { isAvailable }) => isAvailable,
            },
        ],
        runJobAvailableTimeout: [
            null as number | null,
            {
                setRunJobAvailableTimeout: (_, { timeout }) => timeout,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        playButtonOnClick: ({ jobHasEmptyPayload }) => {
            if (!values.runJobAvailable) {
                return
            }
            if (jobHasEmptyPayload) {
                actions.submitJobPayload()
                return
            }
            actions.setIsJobModalOpen(true)
        },
    })),
    forms(({ actions, props, values }) => ({
        jobPayload: {
            defaults: Object.fromEntries(
                Object.entries(props.jobSpec.payload || {})
                    .filter(([, spec]) => 'default' in spec)
                    .map(([key, spec]) => [key, spec.default])
            ) as Record<string, any>,

            errors: (payload: Record<string, any>) => {
                const errors = {}
                for (const key of Object.keys(props.jobSpec.payload || {})) {
                    const spec = props.jobSpec.payload?.[key]
                    if (spec?.required && payload[key] == undefined) {
                        errors[key] = 'Please enter a value'
                    } else if (spec?.type == 'json' && !validateJson(payload[key])) {
                        errors[key] = 'Please enter valid JSON'
                    }
                }
                return errors
            },

            submit: async (payload) => {
                actions.setIsJobModalOpen(false)

                try {
                    await api.create(`api/plugin_config/${props.pluginConfigId}/job`, {
                        job: {
                            type: props.jobName,
                            payload,
                        },
                    })
                } catch (error) {
                    lemonToast.error(`Enqueuing job "${props.jobName}" failed`)
                    return
                }

                props.onSubmit?.()

                // temporary handling to prevent people from rage
                // clicking and creating multiple jobs - this will be
                // subsituted by better feedback tools like progress bars
                actions.setRunJobAvailable(false)
                if (values.runJobAvailableTimeout) {
                    clearTimeout(values.runJobAvailableTimeout)
                }
                const timeout = window.setTimeout(() => {
                    actions.setRunJobAvailable(true)
                }, 15000)
                actions.setRunJobAvailableTimeout(timeout)

                lemonToast.success('Job has been enqueued')
            },
        },
    })),
    events(({ values }) => ({
        beforeUnmount: () => {
            if (values.runJobAvailableTimeout) {
                clearTimeout(values.runJobAvailableTimeout)
            }
        },
    })),
])
