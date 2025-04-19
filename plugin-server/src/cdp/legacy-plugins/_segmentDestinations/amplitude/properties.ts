import { InputField } from '@segment/actions-core/destination-kit/types'

export const userAgentData: InputField = {
  label: 'User Agent Data',
  type: 'object',
  description: 'The user agent data of device sending the event',
  properties: {
    model: {
      label: 'Model',
      type: 'string'
    },
    platformVersion: {
      label: 'PlatformVersion',
      type: 'string'
    }
  },
  default: {
    model: { '@path': '$.context.userAgentData.model' },
    platformVersion: { '@path': '$.context.userAgentData.platformVersion' }
  }
}
