import {createHash} from 'crypto'
import {existsSync, mkdtempSync, readFileSync, rmSync} from 'fs'
import {tmpdir} from 'os'
import * as path from 'path'
import {command, CommandOptions, configureCopyClient} from './shared-image-command'
import {DIGEST, ORDERED_ALIAS, REVISION, CANONICAL_SOURCE_REPOSITORY, DestinationBinding, ImageBinding} from './shared-image-releases'

export type Outcome = 'present-at-expected-digest' | 'absent' | 'integrity-mismatch' | 'unknown'
export interface Publication {
  outcome: Outcome
  reason?: string
}
export interface RegistryBudgets {
  registryMs: number
  copySeconds: number
  readbackSeconds: number
  maxBuffer: number
}
export interface ImageIdentity {
  revision: string
  digest: string
}
export interface Inventory {
  tags: Set<string>
  nonempty: boolean
}

export class ReleaseRegistry {
  constructor(
    private readonly cwd: string, private readonly regctl: string,
    private readonly helper: string, private readonly budgets: RegistryBudgets,
    private readonly deadline: number
  ) {
    this.regctl = configureCopyClient(regctl)
  }

  private options(timeoutMs = this.budgets.registryMs): CommandOptions {
    return {cwd: this.cwd, maxBuffer: this.budgets.maxBuffer, timeoutMs: Math.min(timeoutMs, this.deadline - Date.now())}
  }

  private aws(destination: DestinationBinding, args: string[]): Promise<string> {
    return command('aws', ['ecr', ...args, '--registry-id', destination.registry.split('.')[0],
      '--repository-name', destination.repository], this.options())
  }

  async list(destination: DestinationBinding): Promise<Inventory> {
    const tags = new Set<string>()
    const tokens = new Set<string>()
    let token: string | undefined
    let nonempty = false
    do {
      const page = JSON.parse(await this.aws(destination, [
        'list-images', '--no-paginate', '--max-results', '1000', '--output', 'json',
        ...(token ? ['--next-token', token] : [])
      ])) as {imageIds?: {imageTag?: string; imageDigest?: string}[]; nextToken?: string}
      if (!Array.isArray(page.imageIds)) throw new Error(`${destination.repository}: invalid frontier page`)
      nonempty ||= page.imageIds.length > 0
      for (const image of page.imageIds) {
        if (image.imageTag !== undefined && typeof image.imageTag !== 'string') throw new Error('Invalid frontier tag')
        if (image.imageTag) tags.add(image.imageTag)
      }
      token = page.nextToken
      if (token !== undefined && (typeof token !== 'string' || !token || tokens.has(token))) {
        throw new Error(`${destination.repository}: invalid or repeated pagination token`)
      }
      if (token) tokens.add(token)
    } while (token)
    return {tags, nonempty}
  }

  async read(destination: DestinationBinding, tag: string): Promise<string | undefined> {
    const digest = (await this.aws(destination, [
      'batch-get-image', '--image-ids', `imageTag=${tag}`, '--accepted-media-types',
      'application/vnd.oci.image.index.v1+json', 'application/vnd.docker.distribution.manifest.list.v2+json',
      'application/vnd.oci.image.manifest.v1+json', 'application/vnd.docker.distribution.manifest.v2+json',
      '--query', 'images[0].imageId.imageDigest', '--output', 'text'
    ])).trim()
    if (digest === 'None') return undefined
    if (!DIGEST.test(digest)) throw new Error(`${destination.repository}:${tag}: invalid image digest`)
    return digest
  }

  async identity(registry: string, repository: string, digest: string, tag?: string): Promise<ImageIdentity> {
    if (!DIGEST.test(digest)) throw new Error('Expected exact image digest')
    const raw = await command('client', ['manifest', 'get', `${registry}/${repository}@${digest}`, '--format', 'raw-body'], {
      ...this.options(), env: {REGCTL: this.regctl}
    })
    if (`sha256:${createHash('sha256').update(raw, 'utf8').digest('hex')}` !== digest) throw new Error('Manifest digest mismatch')
    const manifest = JSON.parse(raw) as {annotations?: Record<string, string>}
    const revision = manifest.annotations?.['org.opencontainers.image.revision'] ?? ''
    const source = manifest.annotations?.['org.opencontainers.image.source']
    if (!REVISION.test(revision) || source !== `https://github.com/${CANONICAL_SOURCE_REPOSITORY}`) {
      throw new Error(`${repository}: invalid canonical source/revision metadata`)
    }
    if (tag && (!ORDERED_ALIAS.test(tag) || tag.slice(14) !== revision.slice(0, 6))) {
      throw new Error(`${repository}:${tag}: alias revision mismatch`)
    }
    return {revision, digest}
  }

  async publish(source: ImageBinding, destination: DestinationBinding, digest: string, tag: string): Promise<Publication> {
    const scratch = mkdtempSync(path.join(tmpdir(), 'ordered-image-'))
    const output = path.join(scratch, 'output')
    try {
      const logs = await command('helper', [this.helper, 'publish'], {
        ...this.options((this.budgets.copySeconds + this.budgets.readbackSeconds + 15) * 1000),
        env: {
          SOURCE_REGISTRY: source.registry, SOURCE_REPO: source.repository,
          ECR_REGISTRY: destination.registry, ECR_REPO: destination.repository,
          EXPECTED_DIGEST: digest, ORDERED_ALIAS: tag, REGCTL: this.regctl, GITHUB_OUTPUT: output,
          COPY_TIMEOUT_SECONDS: String(this.budgets.copySeconds), READBACK_TIMEOUT_SECONDS: String(this.budgets.readbackSeconds)
        }
      })
      process.stdout.write(logs)
      const match = existsSync(output) ? /^outcome=(present-at-expected-digest|absent|integrity-mismatch|unknown)$/m.exec(readFileSync(output, 'utf8')) : undefined
      return match ? {outcome: match[1] as Outcome} : {outcome: 'unknown', reason: 'Publication helper produced no recognized outcome'}
    } catch (error) {
      process.stderr.write(`${String(error)}\n`)
      return {outcome: 'unknown', reason: String(error)}
    } finally {
      rmSync(scratch, {recursive: true, force: true})
    }
  }
}
