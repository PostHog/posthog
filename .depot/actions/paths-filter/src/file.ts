export interface File {
  filename: string
  status: ChangeStatus
}

export enum ChangeStatus {
  Added = 'added',
  Copied = 'copied',
  Deleted = 'deleted',
  Modified = 'modified',
  Renamed = 'renamed',
  Unmerged = 'unmerged'
}

export interface ApiFileRow {
  filename: string
  status: string
  // 'previous_filename' for some unknown reason isn't in the type definition or documentation
  previous_filename?: string
}

// Translates one row of `GET /pulls/{n}/files` into the shape `git diff --no-renames`
// produces, so the API and merge-commit detection paths return the same list.
export function normalizeApiFile(row: ApiFileRow): File[] {
  // There's no obvious use-case for detection of renames.
  // Rename is replaced by delete of original filename and add of new filename.
  if (row.status === ChangeStatus.Renamed) {
    return [
      {filename: row.filename, status: ChangeStatus.Added},
      {filename: row.previous_filename as string, status: ChangeStatus.Deleted}
    ]
  }

  // Github status and git status variants are same except for deleted files
  const status = row.status === 'removed' ? ChangeStatus.Deleted : (row.status as ChangeStatus)
  return [{filename: row.filename, status}]
}
