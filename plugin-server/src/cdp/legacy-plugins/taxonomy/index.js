const transformations = [
    {
        name: "camelCase",
        matchPattern: /[A-Z]/g,
        transform: (str, matchPattern) => str[0].toLowerCase()  + str.slice(1).replace(matchPattern, (substr) => substr[substr.length-1].toUpperCase())
    },
    {
        name: "PascalCase",
        matchPattern: /[A-Z]/g,
        transform: (str, matchPattern) => str[0].toUpperCase() + str.slice(1).replace(matchPattern, (substr) => substr[substr.length-1].toUpperCase())
    },
    {
        name: "snake_case",
        matchPattern: /([_])([a-z])/g,
        transform: (str, matchPattern) => defaultTransformation(str, matchPattern, '_')
    },
    {
        name: "kebab_case",
        matchPattern: /([-])([a-z])/g,
        transform: (str, matchPattern) => defaultTransformation(str, matchPattern, '-')
    },
    {
        name: "spaces",
        matchPattern: /([\s])([a-z])/g,
        transform: (str, matchPattern) => defaultTransformation(str, matchPattern, ' ')
    },
] 

const configSelectionMap = {
    "camelCase": 0,
    "PascalCase": 1,
    "snake_case": 2,
    "kebab-case": 3,
    "spaces in between": 4
}

const skippedPostHogEvents = [
    'survey shown',
    'survey sent',
    'survey dismissed',
]


async function processEventBatch(events, { config }) {
    for (let event of events) {
        if (!event.event.startsWith("$") && !skippedPostHogEvents.includes(event.event)) {
            event.event = standardizeName(event.event, transformations[configSelectionMap[config.defaultNamingConvention]])
        }
    }
    return events
}


const defaultTransformation = (str, matchPattern, sep) => {
    const parsedStr = str.replace(
        matchPattern, 
        (substr) => sep + (substr.length === 1 ?  substr.toLowerCase() : substr[1].toLowerCase())
    )
    if (parsedStr[0] === sep) {
        return parsedStr.slice(1) // Handle PascalCase
    }
    return parsedStr
}


const standardizeName = (name, desiredPattern) => {
    for (const transformation of transformations) {
        if (transformation.name === desiredPattern.name || name.search(transformation.matchPattern) < 0) {
            continue
        }
        return desiredPattern.transform(name, transformation.matchPattern)
    }
    return name
}

module.exports = {
    processEventBatch
}