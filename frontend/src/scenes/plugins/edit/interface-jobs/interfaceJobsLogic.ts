import type { FormInstance } from 'antd/lib/form/hooks/useForm.d'
import { kea } from 'kea'
import api from 'lib/api'
import { interfaceJobsLogicType } from './interfaceJobsLogicType'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { JobSpec } from '~/types'
import { lemonToast } from 'lib/components/lemonToast'

export const interfaceJobsLogic = kea<interfaceJobsLogicType>({
    props: {} as {
        jobName: string
        pluginConfigId: number
        pluginId: number
        jobSpecPayload: JobSpec['payload']
    },
    key: (props) => {
        return `${props.pluginId}_${props.jobName}`
    },
    path: (key) => ['scenes', 'plugins', 'edit', 'interface-jobs', 'interfaceJobsLogic', key],
    connect: {
        actions: [pluginsLogic, ['showPluginLogs']],
    },
    actions: {
        setIsJobModalOpen: (isOpen: boolean) => ({ isOpen }),
        setRunJobAvailable: (isAvailable: boolean) => ({ isAvailable }),
        runJob: (form: FormInstance<any>) => ({ form }),
        playButtonOnClick: (form: FormInstance<any>, jobHasEmptyPayload: boolean) => ({ form, jobHasEmptyPayload }),
        setRunJobAvailableTimeout: (timeout: number) => ({ timeout }),
    },
    reducers: {
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
    },
    listeners: ({ actions, props, values }) => ({
        runJob: async ({ form }) => {
            try {
                await form.validateFields()
            } catch {
                return
            }
            actions.setIsJobModalOpen(false)
            const formValues = form.getFieldsValue()

            for (const [fieldKey, fieldValue] of Object.entries(formValues)) {
                if (props.jobSpecPayload?.[fieldKey].type === 'date') {
                    if (!!formValues[fieldKey]) {
                        formValues[fieldKey] = (fieldValue as moment.Moment).toISOString()
                    } else {
                        formValues[fieldKey] = null
                    }
                }
            }
            try {
                await api.create(`api/plugin_config/${props.pluginConfigId}/job`, {
                    job: {
                        type: props.jobName,
                        payload: form.getFieldsValue(),
                    },
                })
            } catch (error) {
                lemonToast.error(`Enqueuing job "${props.jobName}" failed`)
                return
            }

            actions.showPluginLogs(props.pluginId)

            // temporary handling to prevent people from rage
            // clicking and creating multiple jobs - this will be
            // subsituted by better feedback tools like progress bars
            actions.setRunJobAvailable(false)
            if (values.runJobAvailableTimeout) {
                clearTimeout(values.runJobAvailableTimeout)
            }
            const timeout = window.setTimeout(() => {
                actions.setRunJobAvailable(true)
                actions.setRunJobAvailableTimeout(timeout)
            }, 15000)

            lemonToast.success('Job has been enqueued')
        },
        playButtonOnClick: ({ form, jobHasEmptyPayload }) => {
            if (!values.runJobAvailable) {
                return
            }
            if (jobHasEmptyPayload) {
                actions.runJob(form)
                return
            }
            actions.setIsJobModalOpen(true)
        },
    }),
    events: ({ values }) => ({
        beforeUnmount: () => {
            if (values.runJobAvailableTimeout) {
                clearTimeout(values.runJobAvailableTimeout)
            }
        },
    }),
})
