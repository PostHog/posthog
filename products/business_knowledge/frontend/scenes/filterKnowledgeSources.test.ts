import type { KnowledgeSourceApi } from '../generated/api.schemas'
import {
    filterKnowledgeSources,
    type KnowledgeSourceListFilters,
    type SourceTypeFilter,
} from './filterKnowledgeSources'

function makeSource(overrides: Partial<KnowledgeSourceApi> = {}): KnowledgeSourceApi {
    return {
        id: '11111111-1111-1111-1111-111111111111',
        team_id: 1,
        name: 'Refund policy',
        source_type: 'text',
        is_generated: true,
        status: 'ready',
        error_message: '',
        document_count: 1,
        chunk_count: 3,
        created_at: '2026-09-01T12:00:00Z',
        updated_at: '2026-09-01T12:00:00Z',
        source_url: '',
        last_refresh_at: null,
        last_refresh_status: 'success',
        last_refresh_error: '',
        refresh_interval: 'manual',
        next_refresh_at: null,
        has_unsafe_documents: false,
        embedding_status: 'completed',
        learned_from_ticket_number: 42,
        learned_from_ticket_url: 'https://us.posthog.com/project/1/support/tickets/42',
        crawl_mode: 'single',
        crawl_config: {},
        original_filename: '',
        file_content_type: '',
        file_size_bytes: null,
        always_include: false,
        ...overrides,
    }
}

const sources: KnowledgeSourceApi[] = [
    makeSource(),
    makeSource({
        id: '22222222-2222-2222-2222-222222222222',
        name: 'Billing docs',
        source_type: 'url',
        is_generated: false,
        source_url: 'https://docs.example.com/billing',
        learned_from_ticket_number: null,
        learned_from_ticket_url: null,
    }),
    makeSource({
        id: '33333333-3333-3333-3333-333333333333',
        name: 'Pricing PDF',
        source_type: 'file',
        is_generated: false,
        original_filename: 'pricing-2026.pdf',
        learned_from_ticket_number: null,
        learned_from_ticket_url: null,
    }),
]

const none: KnowledgeSourceListFilters = {
    searchTerm: '',
    sourceTypeFilter: [],
    learnedOnly: false,
}

describe('filterKnowledgeSources', () => {
    it.each<[string, KnowledgeSourceListFilters, string[]]>([
        ['no filters returns every source', none, ['Refund policy', 'Billing docs', 'Pricing PDF']],
        ['search matches name case-insensitively', { ...none, searchTerm: 'billing' }, ['Billing docs']],
        ['search matches URL', { ...none, searchTerm: 'docs.example.com' }, ['Billing docs']],
        ['search matches filename', { ...none, searchTerm: 'pricing-2026' }, ['Pricing PDF']],
        ['search matches learned ticket number', { ...none, searchTerm: '#42' }, ['Refund policy']],
        ['search matches ticket subtitle', { ...none, searchTerm: 'ticket' }, ['Refund policy']],
        ['type filter keeps only URLs', { ...none, sourceTypeFilter: ['url'] as SourceTypeFilter }, ['Billing docs']],
        [
            'type filter ORs multiple types',
            { ...none, sourceTypeFilter: ['url', 'file'] as SourceTypeFilter },
            ['Billing docs', 'Pricing PDF'],
        ],
        ['learned only hides sources you added', { ...none, learnedOnly: true }, ['Refund policy']],
        [
            'type and learned combine as AND',
            { searchTerm: '', sourceTypeFilter: ['text'] as SourceTypeFilter, learnedOnly: true },
            ['Refund policy'],
        ],
        [
            'type and learned can match nothing',
            { searchTerm: '', sourceTypeFilter: ['url'] as SourceTypeFilter, learnedOnly: true },
            [],
        ],
        [
            'search plus type can match nothing',
            { searchTerm: 'refund', sourceTypeFilter: ['file'] as SourceTypeFilter, learnedOnly: false },
            [],
        ],
    ])('%s', (_name, filters, expectedNames) => {
        expect(filterKnowledgeSources(sources, filters).map((source) => source.name)).toEqual(expectedNames)
    })
})
