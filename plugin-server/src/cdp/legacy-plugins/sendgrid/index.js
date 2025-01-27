async function setupPlugin({ config, global }) {
    // With this call we validate the API Key and also we get the list of custom fields, which will be needed
    // to configure the map between PostHog and Sendgrid.
    const fieldsDefResponse = await fetch('https://api.sendgrid.com/v3/marketing/field_definitions', {
        method: 'GET',
        headers: {
            Authorization: `Bearer ${config.sendgridApiKey}`
        }
    })
    if (!statusOk(fieldsDefResponse)) {
        throw new Error('Unable to connect to Sendgrid')
    }

    const fieldsDef = await fieldsDefResponse.json()

    // Custom fields in Sendgrid have a name and an ID. The name is what users configure when they create a custom field,
    // and ID is automatically assigned by Sendgrid.
    // In the config of this plugin, users configure the map between PostHog prop names and Sendgrid custom fields names.
    // Here we resolve the relation and calculate a map between PostHog prop names and Sendgrid custom field IDs.

    let posthogPropsToSendgridCustomFieldNamesMap = {}
    try {
        posthogPropsToSendgridCustomFieldNamesMap = parseCustomFieldsMap(config.customFields)
    } catch (e) {
        console.error(`Invalid format for custom fields: ${e}`)
        throw new Error('Invalid format for custom fields')
    }

    const posthogPropsToSendgridCustomFieldIDsMap = {}
    for (const [posthogProp, sendgridCustomFieldName] of Object.entries(posthogPropsToSendgridCustomFieldNamesMap)) {
        const cfIndex = Object.keys(fieldsDef.custom_fields || {}).filter(
            (key) => fieldsDef.custom_fields[key].name === sendgridCustomFieldName
        )
        if (cfIndex.length !== 1) {
            throw new Error(`Custom field with name ${sendgridCustomFieldName} is not defined in Sendgrid`)
        }
        posthogPropsToSendgridCustomFieldIDsMap[posthogProp] = fieldsDef.custom_fields[cfIndex].id
    }

    global.customFieldsMap = posthogPropsToSendgridCustomFieldIDsMap
}

async function onEvent(event, { config, global }) {
    if (event.event !== '$identify') {
        return
    }
    let contacts = []
    const customFieldsMap = global.customFieldsMap

    const email = getEmailFromIdentifyEvent(event)
    if (email) {
        let sendgridFilteredProps = {}
        let customFields = {}
        for (const [key, val] of Object.entries(event['$set'] ?? {})) {
            if (sendgridPropsMap[key]) {
                sendgridFilteredProps[sendgridPropsMap[key]] = val
            } else if (customFieldsMap[key]) {
                customFields[customFieldsMap[key]] = val
            }
        }
        contacts.push({
            email: email,
            ...sendgridFilteredProps,
            custom_fields: customFields
        })
    }

    if (contacts.length > 0) {
        const exportContactsResponse = await fetch('https://api.sendgrid.com/v3/marketing/contacts', {
            method: 'PUT',
            headers: {
                Authorization: `Bearer ${config.sendgridApiKey}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ contacts: contacts })
        })

        if (!statusOk(exportContactsResponse)) {
            let errorText = ''
            try {
                errorText = await exportContactsResponse.text()
            } catch (e) {
                // noop
            } finally {
                console.error(`Unable to export ${contacts.length} contacts to Sendgrid: ${errorText}`)
                throw new Error(`Unable to export ${contacts.length} contacts to Sendgrid`)
            }
        }
    }
}

function isEmail(email) {
    const re = /^(([^<>()[\]\\.,;:\s@"]+(\.[^<>()[\]\\.,;:\s@"]+)*)|(".+"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/
    return re.test(String(email).toLowerCase())
}

function getEmailFromIdentifyEvent(event) {
    return isEmail(event.distinct_id)
        ? event.distinct_id
        : !!event['$set'] && Object.keys(event['$set']).includes('email')
        ? event['$set']['email']
        : ''
}

function statusOk(res) {
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
    postal_code: 'postal_code'
}

// parseCustomFieldsMap parses custom properties in a format like "myProp1=my_prop1,my_prop2".
function parseCustomFieldsMap(customProps) {
    const result = {}
    if (customProps) {
        customProps.split(',').forEach((prop) => {
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

module.exports = {
    setupPlugin,
    onEvent
}
