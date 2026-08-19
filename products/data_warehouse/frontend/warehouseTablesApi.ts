import { ApiConfig, PaginatedResponse } from 'lib/api'

import { DatabaseSerializedFieldType } from '~/queries/schema/schema-general'
import { DataWarehouseTable, WarehouseTableFileUpload } from '~/types'

import {
    warehouseTablesCreate,
    warehouseTablesCreateFromUploadCreate,
    warehouseTablesDestroy,
    warehouseTablesList,
    warehouseTablesPartialUpdate,
    warehouseTablesRefreshSchemaCreate,
    warehouseTablesRetrieve,
    warehouseTablesUpdateSchemaCreate,
    warehouseTablesUploadFileCreate,
} from './generated/api'
import type { WarehouseTablesListParams } from './generated/api.schemas'

// nosemgrep: prefer-codegen-api
const projectId = (): string => String(ApiConfig.getCurrentProjectId())

type TableListParams = WarehouseTablesListParams & { include_columns?: boolean }

export const generatedWarehouseTablesApi = {
    async list(params?: TableListParams): Promise<PaginatedResponse<DataWarehouseTable>> {
        return (await warehouseTablesList(
            projectId(),
            params as WarehouseTablesListParams
        )) as unknown as PaginatedResponse<DataWarehouseTable>
    },
    async get(tableId: string): Promise<DataWarehouseTable> {
        return (await warehouseTablesRetrieve(projectId(), tableId)) as unknown as DataWarehouseTable
    },
    async create(data: Partial<DataWarehouseTable>): Promise<DataWarehouseTable> {
        return (await warehouseTablesCreate(
            projectId(),
            data as Parameters<typeof warehouseTablesCreate>[1]
        )) as unknown as DataWarehouseTable
    },
    async delete(tableId: string): Promise<void> {
        await warehouseTablesDestroy(projectId(), tableId)
    },
    async update(tableId: string, data: Pick<DataWarehouseTable, 'name'>): Promise<DataWarehouseTable> {
        return (await warehouseTablesPartialUpdate(projectId(), tableId, data)) as unknown as DataWarehouseTable
    },
    async updateSchema(tableId: string, updates: Record<string, DatabaseSerializedFieldType>): Promise<void> {
        await warehouseTablesUpdateSchemaCreate(projectId(), tableId, { updates } as unknown as Parameters<
            typeof warehouseTablesUpdateSchemaCreate
        >[2])
    },
    async refreshSchema(tableId: string): Promise<void> {
        await warehouseTablesRefreshSchemaCreate(projectId(), tableId)
    },
    async uploadFile(data: FormData): Promise<WarehouseTableFileUpload> {
        return (await warehouseTablesUploadFileCreate(projectId(), {
            file: data.get('file') as Blob,
            file_format: data.get('file_format') as NonNullable<
                Parameters<typeof warehouseTablesUploadFileCreate>[1]
            >['file_format'],
        })) as WarehouseTableFileUpload
    },
    async createFromUpload(
        data: Parameters<typeof warehouseTablesCreateFromUploadCreate>[1]
    ): Promise<DataWarehouseTable> {
        return (await warehouseTablesCreateFromUploadCreate(projectId(), data)) as unknown as DataWarehouseTable
    },
}
