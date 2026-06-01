export interface HogTaggerExample {
    label: string
    source: string
}

export const HOG_TAGGER_EXAMPLES: HogTaggerExample[] = [
    {
        label: 'Keyword matching',
        source: `// Tag based on keywords in the output
// Globals: input, output, properties, event, tags
let result := []
if (output ilike '%billing%' or output ilike '%invoice%' or output ilike '%payment%') {
    result := arrayPushBack(result, 'billing')
}
if (output ilike '%feature flag%' or output ilike '%flag%' or output ilike '%rollout%') {
    result := arrayPushBack(result, 'feature-flags')
}
if (output ilike '%analytics%' or output ilike '%dashboard%' or output ilike '%insight%') {
    result := arrayPushBack(result, 'analytics')
}
print(concat('Found ', toString(length(result)), ' tags'))
return result`,
    },
    {
        label: 'Error detection',
        source: `// Tag generations that contain error patterns
let result := []
let patterns := [
    ['error', 'contains-error'],
    ['exception', 'contains-error'],
    ['traceback', 'contains-error'],
    ['sorry', 'apology'],
    ['I cannot', 'refusal'],
    ['I can\\'t', 'refusal']
]
for (let i, pair in patterns) {
    if (output ilike concat('%', pair.1, '%') and not has(result, pair.2)) {
        result := arrayPushBack(result, pair.2)
        print(concat('Matched "', pair.1, '" -> ', pair.2))
    }
}
return result`,
    },
    {
        label: 'Response length',
        source: `// Tag by response length
let len := length(output)
if (len == 0) {
    print('Empty response')
    return ['empty']
} else if (len < 50) {
    print(concat('Short: ', toString(len), ' chars'))
    return ['short']
} else if (len > 2000) {
    print(concat('Long: ', toString(len), ' chars'))
    return ['long']
} else {
    print(concat('Medium: ', toString(len), ' chars'))
    return ['medium']
}`,
    },
    {
        label: 'Model-based',
        source: `// Tag based on which model was used
let model := ifNull(properties.$ai_model, 'unknown')
let result := []
if (model ilike '%gpt%') {
    result := arrayPushBack(result, 'openai')
} else if (model ilike '%claude%') {
    result := arrayPushBack(result, 'anthropic')
} else if (model ilike '%gemini%') {
    result := arrayPushBack(result, 'google')
} else {
    result := arrayPushBack(result, 'other')
}
print(concat('Model: ', model))
return result`,
    },
    {
        label: 'Cost tiers',
        source: `// Tag by cost tier
let cost := ifNull(properties.$ai_total_cost_usd, 0)
if (cost == 0) {
    return ['free']
} else if (cost < 0.01) {
    return ['cheap']
} else if (cost < 0.10) {
    return ['moderate']
} else {
    print(concat('Expensive: $', toString(cost)))
    return ['expensive']
}`,
    },
    {
        label: 'Roles found',
        source: `// Tag which message roles and features appear in the conversation
let result := []
let combined := concat(input, ' ', output)
let roles := ['system', 'user', 'assistant', 'tool', 'function']
for (let i, role in roles) {
    if (combined ilike concat('%"role": "', role, '"%') or combined ilike concat('%"role":"', role, '"%')) {
        result := arrayPushBack(result, concat('has-', role))
        print(concat('Found role: ', role))
    }
}
if (combined ilike '%"tool_calls"%' or combined ilike '%"function_call"%') {
    result := arrayPushBack(result, 'has-tool-calls')
    print('Found tool calls')
}
if (length(result) == 0) {
    result := arrayPushBack(result, 'no-roles')
}
return result`,
    },
    {
        label: 'Language detection',
        source: `// Simple language detection based on common words
let result := []
if (output ilike '% the %' or output ilike '% is %' or output ilike '% and %') {
    result := arrayPushBack(result, 'english')
}
if (output ilike '% le %' or output ilike '% est %' or output ilike '% les %') {
    result := arrayPushBack(result, 'french')
}
if (output ilike '% der %' or output ilike '% ist %' or output ilike '% und %') {
    result := arrayPushBack(result, 'german')
}
if (output ilike '% el %' or output ilike '% es %' or output ilike '% los %') {
    result := arrayPushBack(result, 'spanish')
}
if (length(result) == 0) {
    result := arrayPushBack(result, 'other')
}
return result`,
    },
]
