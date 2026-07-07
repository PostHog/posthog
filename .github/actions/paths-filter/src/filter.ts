import * as jsyaml from 'js-yaml'
import picomatch from 'picomatch'
import {File, ChangeStatus} from './file'

// Type definition of object we expect to load from YAML
interface FilterYaml {
  [name: string]: FilterItemYaml
}
type FilterItemYaml =
  | string // Filename pattern, e.g. "path/to/*.js"
  | {[changeTypes: string]: string | string[]} // Change status and filename, e.g. added|modified: "path/to/*.js"
  | FilterItemYaml[] // Supports referencing another rule via YAML anchor

// Minimatch options used in all matchers
const MatchOptions = {
  dot: true
}

// Internal representation of one item in named filter rule
// Created as simplified form of data in FilterItemYaml
interface FilterRuleItem {
  status?: ChangeStatus[] // Required change status of the matched files
  negated: boolean // Whether the source pattern was a '!' negation
  isMatch: (str: string) => boolean // Matches the filename against the positive glob
}

// A leading '!' negates the pattern, unless it opens an extglob group ('!(...)')
function isNegatedPattern(pattern: string): boolean {
  return pattern.startsWith('!') && pattern.charAt(1) !== '('
}

function positivePattern(pattern: string): string {
  return isNegatedPattern(pattern) ? pattern.slice(1) : pattern
}

export interface FilterResults {
  [key: string]: File[]
}

export class Filter {
  rules: {[key: string]: FilterRuleItem[]} = {}

  // Creates instance of Filter and load rules from YAML if it's provided
  constructor(yaml?: string) {
    if (yaml) {
      this.load(yaml)
    }
  }

  // Load rules from YAML string
  load(yaml: string): void {
    if (!yaml) {
      return
    }

    const doc = jsyaml.load(yaml) as FilterYaml
    if (typeof doc !== 'object') {
      this.throwInvalidFormatError('Root element is not an object')
    }

    for (const [key, item] of Object.entries(doc)) {
      this.rules[key] = this.parseFilterItemYaml(item)
    }
  }

  match(files: File[]): FilterResults {
    const result: FilterResults = {}
    for (const [key, patterns] of Object.entries(this.rules)) {
      result[key] = files.filter(file => this.isMatch(file, patterns))
    }
    return result
  }

  // Positive patterns are includes, OR-ed together; every '!' pattern is an exclude
  // that vetoes a match. A file matches when it hits at least one include (or there
  // are no includes) and hits no exclude.
  private isMatch(file: File, patterns: FilterRuleItem[]): boolean {
    const matches = (rule: Readonly<FilterRuleItem>): boolean =>
      (rule.status === undefined || rule.status.includes(file.status)) && rule.isMatch(file.filename)

    const includes = patterns.filter(rule => !rule.negated)
    const excludes = patterns.filter(rule => rule.negated)

    const included = includes.length === 0 || includes.some(matches)
    const excluded = excludes.some(matches)
    return included && !excluded
  }

  private parseFilterItemYaml(item: FilterItemYaml): FilterRuleItem[] {
    if (Array.isArray(item)) {
      return flat(item.map(i => this.parseFilterItemYaml(i)))
    }

    if (typeof item === 'string') {
      return [
        {status: undefined, negated: isNegatedPattern(item), isMatch: picomatch(positivePattern(item), MatchOptions)}
      ]
    }

    if (typeof item === 'object') {
      return Object.entries(item).map(([key, pattern]) => {
        if (typeof key !== 'string' || (typeof pattern !== 'string' && !Array.isArray(pattern))) {
          this.throwInvalidFormatError(
            `Expected [key:string]= pattern:string | string[], but [${key}:${typeof key}]= ${pattern}:${typeof pattern} found`
          )
        }
        const negated = typeof pattern === 'string' && isNegatedPattern(pattern)
        return {
          status: key
            .split('|')
            .map(x => x.trim())
            .filter(x => x.length > 0)
            .map(x => x.toLowerCase()) as ChangeStatus[],
          negated,
          isMatch: picomatch(negated ? positivePattern(pattern as string) : pattern, MatchOptions)
        }
      })
    }

    this.throwInvalidFormatError(`Unexpected element type '${typeof item}'`)
  }

  private throwInvalidFormatError(message: string): never {
    throw new Error(`Invalid filter YAML format: ${message}.`)
  }
}

// Creates a new array with all sub-array elements concatenated
// In future could be replaced by Array.prototype.flat (supported on Node.js 11+)
function flat<T>(arr: T[][]): T[] {
  return arr.reduce((acc, val) => acc.concat(val), [])
}
