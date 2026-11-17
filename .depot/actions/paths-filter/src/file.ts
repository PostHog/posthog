export interface File {
  filename: string
  status: ChangeStatus
  sha?: string
}

export interface ApiFileRow {
  filename: string
  status: string
  sha?: string | null
  previous_filename?: string
}

export function filesFromApiRow(row: ApiFileRow): File[] {
  if (row.status === ChangeStatus.Renamed) {
    return [
      {filename: row.filename, status: ChangeStatus.Added, sha: row.sha ?? undefined},
      {filename: row.previous_filename as string, status: ChangeStatus.Deleted}
    ]
  }
  if (row.status === 'removed') {
    return [{filename: row.filename, status: ChangeStatus.Deleted}]
  }
  return [{filename: row.filename, status: row.status as ChangeStatus, sha: row.sha ?? undefined}]
}

export enum ChangeStatus {
  Added = 'added',
  Copied = 'copied',
  Deleted = 'deleted',
  Modified = 'modified',
  Renamed = 'renamed',
  Unmerged = 'unmerged'
}
