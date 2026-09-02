import { ContainerModule } from "inversify";
import { SPEECH_QUEUE_SERVICE } from "./identifiers";
import { SpeechQueueService } from "./speech";

export const speechCoreModule = new ContainerModule(({ bind }) => {
  bind(SPEECH_QUEUE_SERVICE).to(SpeechQueueService).inSingletonScope();
});
