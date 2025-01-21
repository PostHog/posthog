/**
 *
 * DO NOT EDIT THIS FILE UNLESS IT IS IN /costs
 */

import { ModelDetailsMap, ModelRow } from '../../../types'

const costs: ModelRow[] = [
    {
        model: {
            operator: 'equals',
            value: 'ada',
        },
        cost: {
            prompt_token: 0.0000004,
            completion_token: 0.0000004,
        },
    },
    {
        model: {
            operator: 'equals',
            value: 'text-ada-001',
        },
        cost: {
            prompt_token: 0.0000004,
            completion_token: 0.0000004,
        },
    },
    {
        model: {
            operator: 'equals',
            value: 'babbage',
        },
        cost: {
            prompt_token: 0.0000005,
            completion_token: 0.0000005,
        },
    },
    {
        model: {
            operator: 'equals',
            value: 'curie',
        },
        cost: {
            prompt_token: 0.000002,
            completion_token: 0.000002,
        },
    },
    {
        model: {
            operator: 'equals',
            value: 'text-curie-001',
        },
        cost: {
            prompt_token: 0.000002,
            completion_token: 0.000002,
        },
    },
    {
        model: {
            operator: 'equals',
            value: 'davinci',
        },
        cost: {
            prompt_token: 0.00002,
            completion_token: 0.00002,
        },
    },
    {
        model: {
            operator: 'equals',
            value: 'text-davinci-001',
        },
        cost: {
            prompt_token: 0.00002,
            completion_token: 0.00002,
        },
    },
    {
        model: {
            operator: 'equals',
            value: 'text-davinci-002',
        },
        cost: {
            prompt_token: 0.00002,
            completion_token: 0.00002,
        },
    },
    {
        model: {
            operator: 'equals',
            value: 'text-davinci-003',
        },
        cost: {
            prompt_token: 0.00002,
            completion_token: 0.00002,
        },
    },
    {
        model: {
            operator: 'equals',
            value: 'gpt-3.5-turbo',
        },
        cost: {
            prompt_token: 0.0000015,
            completion_token: 0.000002,
        },
        showInPlayground: true,
    },
    {
        model: {
            operator: 'equals',
            value: 'gpt-3.5-turbo-0301',
        },
        cost: {
            prompt_token: 0.0000015,
            completion_token: 0.000002,
        },
        showInPlayground: true,
    },
    {
        model: {
            operator: 'equals',
            value: 'gpt-35-turbo',
        },
        cost: {
            prompt_token: 0.0000015,
            completion_token: 0.000002,
        },
    },
    {
        model: {
            operator: 'equals',
            value: 'gpt-3.5-turbo-1106',
        },
        cost: {
            prompt_token: 0.000001,
            completion_token: 0.000002,
        },
        showInPlayground: true,
    },
    {
        model: {
            operator: 'equals',
            value: 'gpt-3.5-turbo-instruct',
        },
        cost: {
            prompt_token: 0.0000015,
            completion_token: 0.000002,
        },
        showInPlayground: true,
    },
    {
        model: {
            operator: 'equals',
            value: 'gpt-3.5-turbo-instruct-0914',
        },
        cost: {
            prompt_token: 0.0000015,
            completion_token: 0.000002,
        },
        showInPlayground: true,
    },
    {
        model: {
            operator: 'equals',
            value: 'gpt-4',
        },
        cost: {
            prompt_token: 0.00003,
            completion_token: 0.00006,
        },
        showInPlayground: true,
    },
    {
        model: {
            operator: 'equals',
            value: 'gpt-4-0314',
        },
        cost: {
            prompt_token: 0.00003,
            completion_token: 0.00006,
        },
        showInPlayground: true,
    },
    {
        model: {
            operator: 'equals',
            value: 'gpt-4-0613',
        },
        cost: {
            prompt_token: 0.00003,
            completion_token: 0.00006,
        },
        showInPlayground: true,
    },
    {
        model: {
            operator: 'equals',
            value: 'gpt-4-32k',
        },
        cost: {
            prompt_token: 0.00006,
            completion_token: 0.00012,
        },
        showInPlayground: true,
    },
    {
        model: {
            operator: 'equals',
            value: 'gpt-4-32k-0314',
        },
        cost: {
            prompt_token: 0.00006,
            completion_token: 0.00012,
        },
        showInPlayground: true,
    },
    {
        model: {
            operator: 'equals',
            value: 'gpt-4-32k-0613',
        },
        cost: {
            prompt_token: 0.00006,
            completion_token: 0.00012,
        },
        showInPlayground: true,
    },
    {
        model: {
            operator: 'equals',
            value: 'gpt-4-0125-preview',
        },
        cost: {
            prompt_token: 0.00001,
            completion_token: 0.00003,
        },
        showInPlayground: true,
    },
    {
        model: {
            operator: 'equals',
            value: 'gpt-4-1106-preview',
        },
        cost: {
            prompt_token: 0.00001,
            completion_token: 0.00003,
        },
        showInPlayground: true,
    },
    {
        model: {
            operator: 'equals',
            value: 'gpt-4-1106-vision-preview',
        },
        cost: {
            prompt_token: 0.00001,
            completion_token: 0.00003,
        },
        showInPlayground: true,
    },
    {
        model: {
            operator: 'equals',
            value: 'gpt-4o',
        },
        cost: {
            prompt_token: 0.000005,
            completion_token: 0.000015,
        },
        showInPlayground: true,
    },
    {
        model: {
            operator: 'equals',
            value: 'gpt-4o-2024-05-13',
        },
        cost: {
            prompt_token: 0.000005,
            completion_token: 0.000015,
        },
        showInPlayground: true,
    },

    {
        model: {
            operator: 'equals',
            value: 'gpt-4o-mini',
        },
        cost: {
            prompt_token: 0.00000015,
            completion_token: 0.0000006,
        },
        showInPlayground: true,
    },
    {
        model: {
            operator: 'equals',
            value: 'gpt-4o-mini-2024-07-18',
        },
        cost: {
            prompt_token: 0.00000015,
            completion_token: 0.0000006,
        },
        showInPlayground: true,
    },
    {
        model: {
            operator: 'equals',
            value: 'gpt-3.5-turbo-0613',
        },
        cost: {
            prompt_token: 0.0000015,
            completion_token: 0.000002,
        },
        showInPlayground: true,
    },
    {
        model: {
            operator: 'equals',
            value: 'gpt-35-turbo-16k',
        },
        cost: {
            prompt_token: 0.000003,
            completion_token: 0.000004,
        },
    },
    {
        model: {
            operator: 'equals',
            value: 'gpt-3.5-turbo-16k-0613',
        },
        cost: {
            prompt_token: 0.000003,
            completion_token: 0.000004,
        },
        showInPlayground: true,
    },
    {
        model: {
            operator: 'equals',
            value: 'gpt-3.5-turbo-0125',
        },
        cost: {
            prompt_token: 0.0000005,
            completion_token: 0.0000015,
        },
        showInPlayground: true,
    },
    {
        model: {
            operator: 'equals',
            value: 'gpt-4-turbo',
        },
        cost: {
            prompt_token: 0.00001,
            completion_token: 0.00003,
        },
        showInPlayground: true,
    },
    {
        model: {
            operator: 'equals',
            value: 'gpt-4-turbo-2024-04-09',
        },
        cost: {
            prompt_token: 0.00001,
            completion_token: 0.00003,
        },
        showInPlayground: true,
    },
    {
        model: {
            operator: 'equals',
            value: 'gpt-4-turbo-0125-preview',
        },
        cost: {
            prompt_token: 0.00001,
            completion_token: 0.00003,
        },
        showInPlayground: true,
    },
    {
        model: {
            operator: 'equals',
            value: 'text-embedding-ada-002',
        },
        cost: {
            prompt_token: 0.0000001,
            completion_token: 0.0,
        },
    },
    {
        model: {
            operator: 'equals',
            value: 'text-embedding-ada',
        },
        cost: {
            prompt_token: 0.0000001,
            completion_token: 0.0,
        },
    },
    {
        model: {
            operator: 'equals',
            value: 'text-embedding-ada-002-v2',
        },
        cost: {
            prompt_token: 0.0000001,
            completion_token: 0.0,
        },
    },
    {
        model: {
            operator: 'equals',
            value: 'text-embedding-3-small',
        },
        cost: {
            prompt_token: 0.00000002,
            completion_token: 0.0,
        },
    },
    {
        model: {
            operator: 'equals',
            value: 'text-embedding-3-large',
        },
        cost: {
            prompt_token: 0.00000013,
            completion_token: 0.0,
        },
    },
    {
        model: {
            operator: 'equals',
            value: 'gpt-4-vision-preview',
        },
        cost: {
            prompt_token: 0.00001,
            completion_token: 0.00003,
        },
    },
    {
        model: {
            operator: 'equals',
            value: 'gpt-35-turbo-16k-0613',
        },
        showInPlayground: true,
        cost: {
            prompt_token: 0.000003,
            completion_token: 0.000004,
        },
    },
    {
        model: {
            operator: 'equals',
            value: 'gpt-4o-2024-08-06',
        },
        showInPlayground: true,
        cost: {
            prompt_token: 0.0000025,
            completion_token: 0.00001,
        },
    },
    {
        model: {
            operator: 'equals',
            value: 'o1-preview',
        },
        cost: {
            prompt_token: 0.000015,
            completion_token: 0.00006,
        },
        showInPlayground: true,
    },
    {
        model: {
            operator: 'equals',
            value: 'o1-preview-2024-09-12',
        },
        cost: {
            prompt_token: 0.000015,
            completion_token: 0.00006,
        },
        showInPlayground: true,
    },
    {
        model: {
            operator: 'equals',
            value: 'o1-mini',
        },
        cost: {
            prompt_token: 0.000003,
            completion_token: 0.000012,
        },
        showInPlayground: true,
    },
    {
        model: {
            operator: 'equals',
            value: 'o1-mini-2024-09-12',
        },
        cost: {
            prompt_token: 0.000003,
            completion_token: 0.000012,
        },
        showInPlayground: true,
    },
]

const modelDetails: ModelDetailsMap = {
    'gpt-4': {
        matches: [
            'gpt-4',
            'gpt-4-0314',
            'gpt-4-0613',
            'gpt-4-32k',
            'gpt-4-32k-0314',
            'gpt-4-0125-preview',
            'gpt-4-1106-preview',
        ],
        searchTerms: ['gpt 4', 'gpt-4', 'chat gpt 4', '4', 'chat 4'],
        info: {
            maxTokens: 8192,
            releaseDate: '2024-03-13',
            description:
                'GPT-4 is the latest and most advanced model in the GPT series, demonstrating sophisticated capabilities in complex reasoning, theory of mind, and narrative understanding.',
            tradeOffs: [
                'More expensive than GPT-3.5 Turbo',
                'Performance can vary even with temperature=0',
                'May struggle with world-building in absurd scenarios',
            ],
            benchmarks: {
                mmlu: 0.864,
                ifeval: 0.67,
                hellaswag: 0.953,
                bbh: 0.831,
            },
            capabilities: [
                'Advanced reasoning',
                'Theory of mind',
                'Complex narrative understanding',
                'Chain-of-thought processing',
            ],
            strengths: [
                'Strong performance in theory of mind tasks',
                'Ability to track and reason about multiple entities',
                'Can explain its reasoning process',
            ],
            weaknesses: [
                'May struggle with highly abstract or unrealistic scenarios',
                'Output can be non-deterministic even at temperature=0',
                "Performance depends on how 'normal' the scenario is",
            ],
            recommendations: [
                'Complex reasoning and analysis tasks',
                'Professional content creation and editing',
                'Advanced coding and technical problem-solving',
                'Multi-step planning and strategy development',
                'Academic research and paper writing',
                'Detailed technical documentation',
            ],
        },
    },
    'gpt-4o': {
        matches: ['gpt-4o', 'gpt-4o-2024-05-13'],
        searchTerms: ['gpt 4o', 'gpt-4o', 'chat gpt 4o', '4o', 'chat 4o'],
        info: {
            maxTokens: 128000,
            releaseDate: '2024-05-13',
            description:
                'GPT-4 Optimized (GPT-4o) is designed for high performance in reasoning, creativity, and technical tasks while maintaining consistent output quality.',
            tradeOffs: [
                'Higher resource requirements for optimal performance',
                'Increased cost per token for premium capabilities',
                'May require more specific prompting for best results',
                'Larger context window increases memory usage',
                'Response time varies with complexity of task',
            ],
            benchmarks: {
                mmlu: 0.887,
                ifeval: 0.902,
                hellaswag: 0.942,
                bbh: 0.913,
            },
            capabilities: [
                'Advanced reasoning and problem-solving',
                'Strong coding abilities',
                'Mathematical computation',
                'Creative content generation',
                'Technical analysis',
            ],
            strengths: [
                'Consistent output quality',
                'Strong technical performance',
                'Reliable response generation',
                'Broad knowledge base',
            ],
            weaknesses: [
                'May produce overconfident responses',
                'Requires clear prompt engineering',
                'Performance varies with task complexity',
            ],
            recommendations: [
                'Technical and analytical projects',
                'Software development tasks',
                'Mathematical problem-solving',
                'Content creation and analysis',
            ],
        },
    },
    'gpt-4o-mini': {
        matches: ['gpt-4o-mini', 'gpt-4o-mini-2024-07-18'],
        searchTerms: ['gpt 4o mini', 'gpt-4o-mini', 'chat gpt 4o mini', 'chat 4o mini'],
        info: {
            maxTokens: 128000,
            releaseDate: '2024-07-18',
            description:
                'GPT-4o Mini is a cost-optimized variant of GPT-4o, designed for high-efficiency processing while maintaining strong performance. It excels in rapid inference and resource-efficient operations, making it ideal for production deployments requiring a balance of cost and capability.',
            tradeOffs: [
                'Lower cost per token compared to GPT-4o',
                'Reduced latency for faster processing',
                'Smaller model size for efficient deployment',
                'Optimized for common tasks and queries',
                'Balance of performance and resource usage',
            ],
            benchmarks: {
                mmlu: 0.82,
                ifeval: 0.872,
                hellaswag: 0.885,
                truthfulqa: 0.793,
                gsm8k: 0.846,
            },
            capabilities: [
                'Efficient natural language processing',
                'Quick response generation',
                'Code understanding and generation',
                'Task-specific optimization',
                'Resource-efficient inference',
                'Consistent output quality',
                'Scalable deployment support',
            ],
            strengths: [
                'Cost-effective processing',
                'Low latency responses',
                'Efficient resource utilization',
                'Strong performance on common tasks',
                'Reliable output quality',
                'Optimized for production use',
                'Excellent scaling characteristics',
            ],
            weaknesses: [
                'Lower performance on complex reasoning',
                'Reduced capability in specialized domains',
                'Limited context understanding vs larger models',
                'May struggle with nuanced tasks',
                'Less suitable for cutting-edge research',
            ],
            recommendations: [
                'High-volume production deployments',
                'Cost-sensitive applications',
                'Real-time processing needs',
                'Standard NLP tasks',
                'Efficient API integrations',
                'Resource-constrained environments',
                'Scalable system architectures',
            ],
        },
    },
    'gpt-4-turbo': {
        matches: ['gpt-4-turbo', 'gpt-4-turbo-2024-04-09', 'gpt-4-turbo-0125-preview'],
        searchTerms: ['gpt 4 turbo', 'gpt-4-turbo', 'chat gpt 4 turbo', '4 turbo', 'chat 4 turbo'],
        info: {
            maxTokens: 128000,
            releaseDate: '2024-04-09',
            description: 'GPT-4 Turbo is a more recent model that offers a balance between cost and performance.',
            tradeOffs: ['More expensive than GPT-3.5 Turbo'],
            benchmarks: {
                bbh: 0.876,
                hellaswag: 0.942,
                mmlu: 0.865,
            },
            capabilities: [],
            strengths: [],
            weaknesses: [],
            recommendations: [],
        },
    },
    'gpt-3.5-turbo': {
        matches: [
            'gpt-3.5-turbo',
            'gpt-3.5-turbo-0301',
            'gpt-35-turbo',
            'gpt-3.5-turbo-1106',
            'gpt-3.5-turbo-instruct',
            'gpt-3.5-turbo-instruct-0914',
            'gpt-3.5-turbo-0613',
            'gpt-3.5-turbo-16k',
            'gpt-3.5-turbo-16k-0613',
            'gpt-35-turbo-16k',
            'gpt-35-turbo-16k-0613',
            'gpt-3.5-turbo-0125',
        ],
        searchTerms: ['gpt 3.5', 'gpt-3.5', 'chat gpt 3.5', 'chat 3.5'],
        info: {
            maxTokens: 16385,
            releaseDate: '2023-11-06',
            description: 'GPT-3.5 Turbo is a more recent model that offers a balance between cost and performance.',
            tradeOffs: ['More expensive than GPT-3.5 Turbo'],
            benchmarks: {
                hellaswag: 0.855,
                mmlu: 0.698,
            },
            capabilities: [],
            strengths: [],
            weaknesses: [],
            recommendations: [],
        },
    },
    'text-embedding-3': {
        matches: ['text-embedding-3-small', 'text-embedding-3-large'],
        searchTerms: ['text embedding 3', 'text-embedding-3'],
        info: {
            maxTokens: 3072,
            releaseDate: '2022-12-15',
            description: 'Text Embedding 3 is a model that offers a balance between cost and performance.',
            tradeOffs: ['More expensive than GPT-3.5 Turbo'],
            benchmarks: {},
            capabilities: [],
            strengths: [],
            weaknesses: [],
            recommendations: [],
        },
    },
    'text-embedding-ada': {
        matches: ['text-embedding-ada-002', 'text-embedding-ada', 'text-embedding-ada-002-v2'],
        searchTerms: ['text embedding ada', 'text-embedding-ada'],
        info: {
            maxTokens: 1536,
            releaseDate: '2022-12-15',
            description: 'Text Embedding Ada is a model that offers a balance between cost and performance.',
            tradeOffs: ['More expensive than GPT-3.5 Turbo'],
            benchmarks: {},
            capabilities: [],
            strengths: [],
            weaknesses: [],
            recommendations: [],
        },
    },
    'o1-preview': {
        matches: ['o1-preview', 'o1-preview-2024-09-12'],
        searchTerms: ['o1 preview', 'o1-preview', 'chat gpt o1', 'chat gpt o1 preview', 'chat o1', 'chat o1 preview'],
        info: {
            maxTokens: 128000,
            releaseDate: '2024-09-12',
            description: 'O1 Preview is a model that offers a balance between cost and performance.',
            tradeOffs: ['More expensive than GPT-3.5 Turbo'],
            benchmarks: {
                mmlu: 0.908,
            },
            capabilities: [],
            strengths: [],
            weaknesses: [],
            recommendations: [],
        },
    },
    'o1-mini': {
        matches: ['o1-mini', 'o1-mini-2024-09-12'],
        searchTerms: ['o1 mini', 'o1-mini', 'chat gpt o1 mini', 'chat o1 mini'],
        info: {
            maxTokens: 128000,
            releaseDate: '2024-09-12',
            description: 'O1 Mini is a model that offers a balance between cost and performance.',
            tradeOffs: ['More expensive than GPT-3.5 Turbo'],
            benchmarks: {},
            capabilities: [],
            strengths: [],
            weaknesses: [],
            recommendations: [],
        },
    },
    'gpt-4-vision-preview': {
        matches: ['gpt-4-vision-preview', 'gpt-4-1106-vision-preview'],
        searchTerms: ['gpt 4 vision', 'gpt-4-vision', 'gpt 4 vision preview', 'chat gpt 4 vision', 'chat 4 vision'],
        info: {
            maxTokens: 128000,
            releaseDate: '2023-11-06',
            description: 'GPT-4 Vision is a model that offers a balance between cost and performance.',
            tradeOffs: ['More expensive than GPT-3.5 Turbo'],
            benchmarks: {
                bbh: 0.876,
                hellaswag: 0.942,
                mmlu: 0.865,
            },
            capabilities: ['Vision'],
            strengths: ['Can process images'],
            weaknesses: ['More expensive than GPT-3.5 Turbo'],
            recommendations: ['Use for tasks that require image processing'],
        },
    },
}

const reverseModelMap: { [key: string]: string } = {}

for (const parentModel in modelDetails) {
    const details = modelDetails[parentModel]
    details.matches.forEach((modelName) => {
        reverseModelMap[modelName] = parentModel
    })
}

export const openAIProvider = {
    costs,
    modelDetails,
    reverseModelMap,
}
