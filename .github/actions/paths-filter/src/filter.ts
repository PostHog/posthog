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

// picomatch.scan tells a real negation ('!foo/**') from an extglob group ('!(a|b)'),
// so we let the matching library own that rule rather than re-deriving it by hand.
function isNegatedPattern(pattern: string): boolean {
  return picomatch.scan(pattern).negated
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
      const includes = patterns.filter(rule => !rule.negated)
      const excludes = patterns.filter(rule => rule.negated)
      result[key] = files.filter(file => this.isMatch(file, includes, excludes))
    }
    return result
  }

  // Positive patterns are includes, OR-ed together; every '!' pattern is an exclude
  // that vetoes a match. A file matches when it hits at least one include (or there
  // are no includes) and hits no exclude.
  private isMatch(file: File, includes: FilterRuleItem[], excludes: FilterRuleItem[]): boolean {
    const matches = (rule: FilterRuleItem): boolean =>
      (rule.status === undefined || rule.status.includes(file.status)) && rule.isMatch(file.filename)

    const included = includes.length === 0 || includes.some(matches)
    return included && !excludes.some(matches)
  }

  private parseFilterItemYaml(item: FilterItemYaml): FilterRuleItem[] {
    if (Array.isArray(item)) {
      return item.map(i => this.parseFilterItemYaml(i)).flat()
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
