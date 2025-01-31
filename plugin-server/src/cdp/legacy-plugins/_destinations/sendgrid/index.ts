import { ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { LegacyDestinationPlugin, LegacyDestinationPluginMeta } from '../../types'
import metadata from './plugin.json'

export const setupPlugin = async ({ config, global, logger, fetch }: LegacyDestinationPluginMeta): Promise<void> => {
    // With this call we validate the API Key and also we get the list of custom fields, which will be needed
    // to configure the map between PostHog and Sendgrid.
    const fieldsDefResponse = await fetch('https://api.sendgrid.com/v3/marketing/field_definitions', {
        method: 'GET',
        headers: {
            Authorization: `Bearer ${config.sendgridApiKey}`,
        },
    })
    if (!statusOk(fieldsDefResponse)) {
        throw new Error('Unable to connect to Sendgrid')
    }

    const fieldsDef = await fieldsDefResponse.json()

    // Custom fields in Sendgrid have a name and an ID. The name is what users configure when they create a custom field,
    // and ID is automatically assigned by Sendgrid.
    // In the config of this plugin, users configure the map between PostHog prop names and Sendgrid custom fields names.
    // Here we resolve the relation and calculate a map between PostHog prop names and Sendgrid custom field IDs.

    let posthogPropsToSendgridCustomFieldNamesMap: any = {}
    try {
        posthogPropsToSendgridCustomFieldNamesMap = parseCustomFieldsMap(config.customFields)
    } catch (e) {
        logger.error(`Invalid format for custom fields: ${e}`)
        throw new Error('Invalid format for custom fields')
    }

    const posthogPropsToSendgridCustomFieldIDsMap: any = {}
    for (const [posthogProp, sendgridCustomFieldName] of Object.entries(posthogPropsToSendgridCustomFieldNamesMap)) {
        const cfIndex: any = Object.keys(fieldsDef.custom_fields || {}).filter(
            (key) => fieldsDef.custom_fields[key].name === sendgridCustomFieldName
        )
        if (cfIndex.length !== 1) {
            throw new Error(`Custom field with name ${sendgridCustomFieldName} is not defined in Sendgrid`)
        }
        posthogPropsToSendgridCustomFieldIDsMap[posthogProp] = fieldsDef.custom_fields[cfIndex].id
    }

    global.customFieldsMap = posthogPropsToSendgridCustomFieldIDsMap
}

export const onEvent = async (
    event: ProcessedPluginEvent,
    { config, global, logger, fetch }: LegacyDestinationPluginMeta
): Promise<void> => {
    if (event.event !== '$identify') {
        return
    }
    const contacts = []
    const customFieldsMap = global.customFieldsMap

    const email = getEmailFromIdentifyEvent(event)
    if (email) {
        const sendgridFilteredProps: any = {}
        const customFields: any = {}
        for (const [key, val] of Object.entries(event['$set'] ?? {})) {
            if (key in sendgridPropsMap) {
                sendgridFilteredProps[sendgridPropsMap[key as keyof typeof sendgridPropsMap]] = val
            } else if (key in customFieldsMap) {
                customFields[customFieldsMap[key]] = val
            }
        }
        contacts.push({
            email: email,
            ...sendgridFilteredProps,
            custom_fields: customFields,
        })
    }

    if (contacts.length > 0) {
        const exportContactsResponse = await fetch('https://api.sendgrid.com/v3/marketing/contacts', {
            method: 'PUT',
            headers: {
                Authorization: `Bearer ${config.sendgridApiKey}`,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ contacts: contacts }),
        })

        if (!statusOk(exportContactsResponse)) {
            let errorText = ''
            try {
                errorText = await exportContactsResponse.text()
            } catch (e) {
                // noop
            } finally {
                logger.error(`Unable to export ${contacts.length} contacts to Sendgrid: ${errorText}`)
                throw new Error(`Unable to export ${contacts.length} contacts to Sendgrid`)
            }
        }
    }
}

function isEmail(email: any): boolean {
    const re =
        /^(([^<>()[\]\\.,;:\s@"]+(\.[^<>()[\]\\.,;:\s@"]+)*)|(".+"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/
    return re.test(String(email).toLowerCase())
}

function getEmailFromIdentifyEvent(event: any): string {
    return isEmail(event.distinct_id)
        ? event.distinct_id
        : !!event['$set'] && Object.keys(event['$set']).includes('email')
        ? event['$set']['email']
        : ''
}

function statusOk(res: any): boolean {
    return String(res.status)[0] === '2'
}

const sendgridPropsMap = {
    lastName: 'last_name',
    last_name: 'last_name',
    lastname: 'last_name',
    firstName: 'first_name',
    first_name: 'first_name',
    firstname: 'first_name',
    city: 'city',
    country: 'country',
    postCode: 'postal_code',
    post_code: 'postal_code',
    postalCode: 'postal_code',
    postal_code: 'postal_code',
}

// parseCustomFieldsMap parses custom properties in a format like "myProp1=my_prop1,my_prop2".
function parseCustomFieldsMap(customProps: any): any {
    const result: any = {}
    if (customProps) {
        customProps.split(',').forEach((prop: string) => {
            const parts = prop.split('=')
            if (parts.length == 1) {
                result[parts[0]] = parts[0]
            } else if (parts.length == 2) {
                result[parts[0]] = parts[1]
            } else {
                throw new Error(`Bad format in '${prop}'`)
            }
        })
    }
    return result
}

export const sendgridPlugin: LegacyDestinationPlugin = {
    id: 'sendgrid-plugin',
    metadata: metadata as any,
    setupPlugin: setupPlugin as any,
    onEvent,
}
