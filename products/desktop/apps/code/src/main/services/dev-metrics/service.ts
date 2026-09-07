import {
  APP_METRICS_SERVICE,
  type IAppMetrics,
} from "@posthog/platform/app-metrics";
import { TypedEventEmitter } from "@posthog/shared";
import { inject, injectable, preDestroy } from "inversify";
import { logger } from "../../utils/logger";
import {
  DevMetricsEvent,
  type DevMetricsEvents,
  type MetricsSample,
  type ProcessSample,
} from "./schemas";

const log = logger.scope("dev-metrics");

const SAMPLE_INTERVAL_MS = 1000;
const LOOP_LAG_INTERVAL_MS = 250;

@injectable()
export class DevMetricsService extends TypedEventEmitter<DevMetricsEvents> {
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private loopLagTimer: ReturnType<typeof setTimeout> | null = null;
  private lastLoopTick = performance.now();
  private loopLagSamples: number[] = [];
  private subscriberCount = 0;
  private lastSample: MetricsSample | null = null;

  constructor(
    @inject(APP_METRICS_SERVICE) private readonly appMetrics: IAppMetrics,
  ) {
    super();
  }

  acquireSampler(): void {
    this.subscriberCount += 1;
    if (this.subscriberCount === 1) {
      this.startPolling();
    }
  }

  releaseSampler(): void {
    this.subscriberCount = Math.max(0, this.subscriberCount - 1);
    if (this.subscriberCount === 0) {
      this.stopPolling();
    }
  }

  getLastSample(): MetricsSample | null {
    return this.lastSample;
  }

  private startPolling(): void {
    if (this.pollTimer) return;
    log.info("Starting metrics sampler");
    this.startLoopLagProbe();
    void this.collectSample();
    this.pollTimer = setInterval(
      () => void this.collectSample(),
      SAMPLE_INTERVAL_MS,
    );
  }

  private stopPolling(): void {
    if (!this.pollTimer) return;
    log.info("Stopping metrics sampler");
    clearInterval(this.pollTimer);
    this.pollTimer = null;
    this.stopLoopLagProbe();
  }

  private startLoopLagProbe(): void {
    this.lastLoopTick = performance.now();
    const tick = () => {
      const now = performance.now();
      const lag = Math.max(0, now - this.lastLoopTick - LOOP_LAG_INTERVAL_MS);
      this.loopLagSamples.push(lag);
      this.lastLoopTick = now;
      this.loopLagTimer = setTimeout(tick, LOOP_LAG_INTERVAL_MS);
    };
    this.loopLagTimer = setTimeout(tick, LOOP_LAG_INTERVAL_MS);
  }

  private stopLoopLagProbe(): void {
    if (this.loopLagTimer) {
      clearTimeout(this.loopLagTimer);
      this.loopLagTimer = null;
    }
    this.loopLagSamples = [];
  }

  private drainLoopLag(): { avg: number; max: number } {
    if (this.loopLagSamples.length === 0) return { avg: 0, max: 0 };
    const samples = this.loopLagSamples;
    this.loopLagSamples = [];
    const max = Math.max(...samples);
    const avg = samples.reduce((s, v) => s + v, 0) / samples.length;
    return { avg, max };
  }

  private async collectSample(): Promise<void> {
    try {
      const metrics = this.appMetrics.getAppMetrics();
      const processes: ProcessSample[] = metrics.map((m) => ({
        pid: m.pid,
        type: m.type,
        name: m.name,
        cpuPercent: m.cpu?.percentCPUUsage ?? 0,
        memoryMb: (m.memory?.workingSetSize ?? 0) / 1024,
      }));
      const totalCpuPercent = processes.reduce(
        (sum, p) => sum + p.cpuPercent,
        0,
      );
      const totalMemoryMb = processes.reduce((sum, p) => sum + p.memoryMb, 0);
      const heap = process.memoryUsage();
      const loop = this.drainLoopLag();
      const sample: MetricsSample = {
        capturedAt: Date.now(),
        totalCpuPercent,
        totalMemoryMb,
        heapUsedMb: heap.heapUsed / 1024 / 1024,
        heapTotalMb: heap.heapTotal / 1024 / 1024,
        loopLagMs: loop.avg,
        loopLagMaxMs: loop.max,
        processes,
      };
      this.lastSample = sample;
      this.emit(DevMetricsEvent.Sample, sample);
    } catch (error) {
      log.warn("Failed to collect metrics sample", { error });
    }
  }

  @preDestroy()
  cleanup(): void {
    this.stopPolling();
  }
}
