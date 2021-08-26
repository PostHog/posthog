import { FormInstance } from 'antd'
import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { errorToast } from 'lib/utils'

import { interfaceJobsLogicType } from './interfaceJobsLogicType'
export const interfaceJobsLogic = kea<interfaceJobsLogicType>({
    actions: {
        setIsJobModalOpen: (isOpen: boolean) => ({ isOpen }),
        setRunJobAvailable: (isAvailable: boolean) => ({ isAvailable }),
        runJob: (form: FormInstance<any>, jobName: string, pluginConfigId: number) => ({
            form,
            jobName,
            pluginConfigId,
        }),
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
    },
    listeners: ({ actions }) => ({
        runJob: async ({ form, jobName, pluginConfigId }) => {
            try {
                await form.validateFields()
            } catch {
                return
            }
            actions.setIsJobModalOpen(false)
            try {
                await api.create(`api/plugin_config/${pluginConfigId}/job`, {
                    job: {
                        type: jobName,
                        payload: form.getFieldsValue(),
                    },
                })
            } catch (error) {
                errorToast(`Enqueuing job '${jobName}' failed`)
                return
            }

            // temporary handling to prevent people from rage
            // clicking and creating multiple jobs - this will be
            // subsituted by better feedback tools like progress bars
            actions.setRunJobAvailable(false)
            setTimeout(() => {
                actions.setRunJobAvailable(true)
            }, 15000)
            toast.success('Job enqueued succesfully.')
        },
    }),
})
