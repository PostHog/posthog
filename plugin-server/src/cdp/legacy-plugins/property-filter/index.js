async function setupPlugin({ config, global }) {
    global.propertiesToFilter = config.properties.split(',')
}

function recursiveRemoveFilterObject(properties, propertyToFilterParts) {
    // if we've reached the final filter part, then we can remove the key if it exists
    // otherwise recursively go down the properties object with the remaining filter parts
    const currentKey = propertyToFilterParts.shift()
    if (currentKey != undefined && currentKey in properties) {
        if (propertyToFilterParts.length == 0) {
            delete properties[currentKey]
        } else {
            recursiveRemoveFilterObject(properties[currentKey], propertyToFilterParts)
        }
    }
}

async function processEvent(event, { global }) {
    let propertiesCopy = event.properties ? { ...event.properties } : {}

    for (const propertyToFilter of global.propertiesToFilter) {
        if (propertyToFilter === '$ip') {
            delete event.ip
        }

        recursiveRemoveFilterObject(propertiesCopy, propertyToFilter.split('.'))
    }
    
    return { ...event, properties: propertiesCopy }
}

module.exports = {
    setupPlugin,
    processEvent,
}
