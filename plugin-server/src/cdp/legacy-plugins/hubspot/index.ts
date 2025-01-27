import { RetryError } from '@posthog/plugin-scaffold'

const hubspotPropsMap = {
    companyName: 'company',
    company_name: 'company',
    company: 'company',
    lastName: 'lastname',
    last_name: 'lastname',
    lastname: 'lastname',
    firstName: 'firstname',
    first_name: 'firstname',
    firstname: 'firstname',
    phone_number: 'phone',
    phoneNumber: 'phone',
    phone: 'phone',
    website: 'website',
    domain: 'website',
    company_website: 'website',
    companyWebsite: 'website'
}

export async function setupPlugin({ config, global }) {
    try {
        global.hubspotAccessToken = config.hubspotAccessToken

        const authResponse = await fetch(
            `https://api.hubapi.com/crm/v3/objects/contacts?limit=1&paginateAssociations=false&archived=false`,
            {
                headers: {
                    Authorization: `Bearer ${config.hubspotAccessToken}`,
                    'Content-Type': 'application/json'
                }
            }
        )

        if (!statusOk(authResponse)) {
            throw new Error('Unable to connect to Hubspot. Please make sure your API key is correct.')
        }
    } catch (error) {
        throw new RetryError(error)
    }
}

export async function onEvent(event, { config, global }) {
    const triggeringEvents = (config.triggeringEvents || '').split(',')

    if (triggeringEvents.indexOf(event.event) >= 0) {
        const email = getEmailFromEvent(event)

        if (email) {
            const emailDomainsToIgnore = (config.ignoredEmails || '').split(',')
            if (emailDomainsToIgnore.indexOf(email.split('@')[1]) >= 0) {
                return
            }
            await createHubspotContact(
                email,
                {
                    ...(event['$set'] ?? {}),
                    ...(event['properties'] ?? {})
                },
                global.hubspotAccessToken,
                config.additionalPropertyMappings,
                event['timestamp']
            )
        }
    }
}

async function createHubspotContact(email, properties, accessToken, additionalPropertyMappings, eventSendTime) {
    let hubspotFilteredProps = {}
    for (const [key, val] of Object.entries(properties)) {
        if (hubspotPropsMap[key]) {
            hubspotFilteredProps[hubspotPropsMap[key]] = val
        }
    }

    if (additionalPropertyMappings) {
        for (let mapping of additionalPropertyMappings.split(',')) {
            const [postHogProperty, hubSpotProperty] = mapping.split(':')
            if (postHogProperty && hubSpotProperty) {
                // special case to convert an event's timestamp to the format Hubspot uses them
                if (postHogProperty === 'sent_at' || postHogProperty === 'created_at') {
                    const d = new Date(eventSendTime)
                    d.setUTCHours(0, 0, 0, 0)
                    hubspotFilteredProps[hubSpotProperty] = d.getTime()
                } else if (postHogProperty in properties) {
                    hubspotFilteredProps[hubSpotProperty] = properties[postHogProperty]
                }
            }
        }
    }

    const addContactResponse = await fetch(`https://api.hubapi.com/crm/v3/objects/contacts`, {
        method: 'POST',
        headers: {
            Authorization: `Bearer ${accessToken}`,
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ properties: { email: email, ...hubspotFilteredProps } })
    })

    const addContactResponseJson = await addContactResponse.json()

    if (!statusOk(addContactResponse) || addContactResponseJson.status === 'error') {
        const errorMessage = addContactResponseJson.message ?? ''
        console.log(
            `Unable to add contact ${email} to Hubspot. Status Code: ${addContactResponse.status}. Error message: ${errorMessage}`
        )

        if (addContactResponse.status === 409) {
            const existingIdRegex = /Existing ID: ([0-9]+)/
            const existingId = addContactResponseJson.message.match(existingIdRegex)
            console.log(`Attempting to update contact ${email} instead...`)

            const updateContactResponse = await fetch(
                `https://api.hubapi.com/crm/v3/objects/contacts/${existingId[1]}`,
                {
                    method: 'PATCH',
                    headers: {
                        Authorization: `Bearer ${accessToken}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ properties: { email: email, ...hubspotFilteredProps } })
                }
            )

            const updateResponseJson = await updateContactResponse.json()
            if (!statusOk(updateContactResponse)) {
                const errorMessage = updateResponseJson.message ?? ''
                console.log(
                    `Unable to update contact ${email} to Hubspot. Status Code: ${updateContactResponse.status}. Error message: ${errorMessage}`
                )
            } else {
                console.log(`Successfully updated Hubspot Contact for ${email}`)
            }
        }
    } else {
        console.log(`Created Hubspot Contact for ${email}`)
    }
}

function statusOk(res) {
    return String(res.status)[0] === '2'
}

function isEmail(email) {
    const re = /^(([^<>()[\]\\.,;:\s@"]+(\.[^<>()[\]\\.,;:\s@"]+)*)|(".+"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/
    return re.test(String(email).toLowerCase())
}

function getEmailFromEvent(event) {
    if (isEmail(event.distinct_id)) {
        return event.distinct_id
    } else if (event['$set'] && Object.keys(event['$set']).includes('email')) {
        if (isEmail(event['$set']['email'])) {
            return event['$set']['email']
        }
    } else if (event['properties'] && Object.keys(event['properties']).includes('email')) {
        if (isEmail(event['properties']['email'])) {
            return event['properties']['email']
        }
    }

    return null
}
