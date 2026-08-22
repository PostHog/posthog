import { Plus, X } from "@phosphor-icons/react";
import {
  type ImagePresetTool,
  imagePresetTools,
  isDirectlyInstallable,
  type RepoHost,
} from "@posthog/core/billing/imagePreset";
import {
  buildImageSpec,
  imageSpecError,
  imageSpecToYaml,
  setupCommandError,
} from "@posthog/core/billing/imageSpec";
import {
  Button,
  Checkbox,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Text,
} from "@posthog/quill";
import { GitHubRepoPicker } from "@posthog/ui/features/folder-picker/GitHubRepoPicker";
import { useCloudRepoPicker } from "@posthog/ui/features/integrations/useCloudRepoPicker";
import { Stepper } from "@posthog/ui/primitives/Stepper";
import { useId, useState } from "react";

const STEPS = ["Repository", "Tools", "Setup", "Review"] as const;

export interface CustomImagePlan {
  repository: string | null;
  tools: ImagePresetTool[];
  setupCommands: string[];
  /** Build the spec directly, or hand the plan to a builder session. */
  mode: "build" | "builder";
}

interface CustomImageWizardProps {
  open: boolean;
  /** The repository the recommendation was about, preselected. */
  defaultRepository: string | null;
  host: RepoHost;
  creating: boolean;
  onCreate: (plan: CustomImagePlan) => void;
  onCancel: () => void;
}

/**
 * Four steps to a sandbox image: which repository it serves, which tools it
 * carries, what to run so dependencies start warm, and a review of the spec it
 * will build. Nothing is created until the last step resolves.
 */
export function CustomImageWizard({
  open,
  defaultRepository,
  host,
  creating,
  onCreate,
  onCancel,
}: CustomImageWizardProps) {
  const preset = imagePresetTools(host);
  const [step, setStep] = useState(0);
  const [repository, setRepository] = useState<string | null>(
    defaultRepository,
  );
  const [excluded, setExcluded] = useState<ReadonlySet<string>>(new Set());
  // Each line carries an id: removing one must not re-key the rest, or the
  // input the user is typing in loses focus.
  const [setupLines, setSetupLines] = useState<SetupLine[]>([]);
  const repoPickerProps = useCloudRepoPicker();

  const tools = preset.filter((tool) => !excluded.has(tool.id));
  const commands = setupLines
    .map((line) => line.value)
    .filter((command) => command.trim() !== "");
  const plan = { tools, setupCommands: commands, repository };
  const specError = imageSpecError(plan);
  const spec = specError === null ? buildImageSpec(plan) : null;
  // A tool apt cannot install needs a builder session to verify it, so the
  // direct build is only offered when every chosen tool can be written down.
  const needsBuilder = tools.some((tool) => !isDirectlyInstallable(tool));

  const complete = [
    true,
    tools.length > 0 || commands.length > 0,
    commands.every((command) => setupCommandError(command) === null),
    specError === null,
  ];
  const isLastStep = step === STEPS.length - 1;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onCancel();
      }}
    >
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Create a sandbox image</DialogTitle>
          <DialogDescription>
            Cloud runs start from this image instead of installing everything
            first.
          </DialogDescription>
        </DialogHeader>

        <DialogBody>
          <div className="flex flex-col gap-4">
            <Stepper
              labels={STEPS}
              current={step}
              complete={complete}
              onSelect={setStep}
            />

            <div className="min-h-[232px]">
              {step === 0 && (
                <WizardStep
                  title="Which repository does this image serve?"
                  description="The builder clones it to check its dependencies come up, and setup commands run inside a checkout of it. You can leave this out and build a tools-only image."
                >
                  <div className="flex items-center gap-3">
                    <GitHubRepoPicker
                      value={repository}
                      onChange={setRepository}
                      {...repoPickerProps}
                    />
                    {repository && (
                      <Button
                        variant="link-muted"
                        size="sm"
                        onClick={() => setRepository(null)}
                      >
                        Clear
                      </Button>
                    )}
                  </div>
                </WizardStep>
              )}

              {step === 1 && (
                <WizardStep
                  title="Tools on the image"
                  description="Search and output tools an agent reaches for on most runs. Each one is listed with the reason it is here."
                >
                  <ul className="flex flex-col divide-y divide-(--gray-4) rounded-(--radius-3) border border-(--gray-5)">
                    {preset.map((tool) => (
                      <ToolRow
                        key={tool.id}
                        tool={tool}
                        included={!excluded.has(tool.id)}
                        onToggle={() =>
                          setExcluded((current) => {
                            const next = new Set(current);
                            if (next.has(tool.id)) {
                              next.delete(tool.id);
                            } else {
                              next.add(tool.id);
                            }
                            return next;
                          })
                        }
                      />
                    ))}
                  </ul>
                </WizardStep>
              )}

              {step === 2 && (
                <WizardStep
                  title="Setup commands"
                  description={
                    repository
                      ? `Run in a checkout of ${repository} while the image builds, so a run starts with dependencies already warm.`
                      : "Setup commands run inside a repository checkout, so pick a repository on the first step to use them."
                  }
                >
                  <SetupCommands
                    lines={setupLines}
                    disabled={!repository}
                    onChange={setSetupLines}
                  />
                </WizardStep>
              )}

              {step === 3 && (
                <WizardStep
                  title="Review"
                  description="This is what gets built."
                >
                  <dl className="flex flex-col gap-2 text-[12.5px]">
                    <ReviewRow
                      label="Repository"
                      value={repository ?? "None, tools only"}
                    />
                    <ReviewRow
                      label="Tools"
                      value={
                        tools.length > 0
                          ? tools.map((tool) => tool.command).join(", ")
                          : "None"
                      }
                    />
                    <ReviewRow
                      label="Setup"
                      value={
                        commands.length > 0
                          ? `${commands.length} command${commands.length === 1 ? "" : "s"}`
                          : "None"
                      }
                    />
                  </dl>
                  {spec && (
                    <details className="rounded-(--radius-3) border border-(--gray-5) px-3 py-2">
                      <summary className="cursor-pointer text-(--gray-11) text-[12px]">
                        Show the spec this builds
                      </summary>
                      <pre className="mt-2 overflow-x-auto font-mono text-(--gray-11) text-[11.5px] leading-relaxed">
                        {imageSpecToYaml(spec)}
                      </pre>
                    </details>
                  )}
                  {specError && (
                    <Text className="text-(--amber-11) text-[12px]">
                      {specError}
                    </Text>
                  )}
                  {needsBuilder && specError === null && (
                    <Text className="text-(--gray-10) text-[12px]">
                      {tools
                        .filter((tool) => !isDirectlyInstallable(tool))
                        .map((tool) => tool.command)
                        .join(", ")}{" "}
                      need a multi-step install, so a builder session works them
                      out and verifies them inside the image.
                    </Text>
                  )}
                </WizardStep>
              )}
            </div>
          </div>
        </DialogBody>

        <DialogFooter>
          <div className="mr-auto">
            {step > 0 && (
              <Button
                variant="link-muted"
                size="sm"
                onClick={() => setStep(step - 1)}
              >
                Back
              </Button>
            )}
          </div>
          <Button variant="outline" size="sm" onClick={onCancel}>
            Cancel
          </Button>
          {isLastStep ? (
            <>
              <Button
                variant={needsBuilder ? "primary" : "outline"}
                size="sm"
                loading={creating}
                disabled={creating || specError !== null}
                data-attr="cost-management-image-open-builder"
                onClick={() => onCreate({ ...plan, tools, mode: "builder" })}
              >
                Open the builder
              </Button>
              {!needsBuilder && (
                <Button
                  variant="primary"
                  size="sm"
                  loading={creating}
                  disabled={creating || specError !== null}
                  data-attr="cost-management-image-build"
                  onClick={() => onCreate({ ...plan, tools, mode: "build" })}
                >
                  Build it now
                </Button>
              )}
            </>
          ) : (
            <Button
              variant="primary"
              size="sm"
              disabled={complete[step] !== true}
              onClick={() => setStep(step + 1)}
            >
              Next
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function WizardStep({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <Text className="font-medium text-(--gray-12) text-[13px]">
          {title}
        </Text>
        <Text className="text-(--gray-11) text-[12px] leading-snug">
          {description}
        </Text>
      </div>
      {children}
    </div>
  );
}

function ReviewRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-3">
      <dt className="w-20 shrink-0 text-(--gray-10)">{label}</dt>
      <dd className="min-w-0 text-(--gray-12)">{value}</dd>
    </div>
  );
}

function ToolRow({
  tool,
  included,
  onToggle,
}: {
  tool: ImagePresetTool;
  included: boolean;
  onToggle: () => void;
}) {
  const checkboxId = useId();
  return (
    <li>
      <label
        htmlFor={checkboxId}
        className="flex cursor-pointer items-center gap-2.5 px-3 py-1.5 transition-colors hover:bg-(--gray-2) motion-reduce:transition-none"
      >
        <Checkbox
          id={checkboxId}
          checked={included}
          onCheckedChange={onToggle}
          className="shrink-0"
          data-attr={`cost-management-image-tool-${tool.id}`}
        />
        <code
          title={tool.name}
          className={`w-16 shrink-0 font-mono text-[12px] ${included ? "text-(--gray-12)" : "text-(--gray-10)"}`}
        >
          {tool.command}
        </code>
        <Text
          className={`min-w-0 text-[11.5px] leading-snug ${included ? "text-(--gray-11)" : "text-(--gray-9)"}`}
        >
          {tool.reason}
        </Text>
      </label>
    </li>
  );
}

interface SetupLine {
  id: string;
  value: string;
}

function SetupCommands({
  lines,
  disabled,
  onChange,
}: {
  lines: SetupLine[];
  disabled: boolean;
  onChange: (lines: SetupLine[]) => void;
}) {
  const idPrefix = useId();
  return (
    <div className="flex flex-col gap-2">
      {lines.map((line, index) => {
        const error =
          line.value.trim() === "" ? null : setupCommandError(line.value);
        return (
          <div key={line.id} className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <Text className="w-4 shrink-0 text-(--gray-9) text-[11px] tabular-nums">
                {index + 1}
              </Text>
              <Input
                className="h-7 flex-1 font-mono text-[12px]"
                value={line.value}
                disabled={disabled}
                placeholder="pnpm install --frozen-lockfile"
                aria-label={`Setup command ${index + 1}`}
                data-attr={`cost-management-image-setup-${index}`}
                onChange={(event) =>
                  onChange(
                    lines.map((current) =>
                      current.id === line.id
                        ? { ...current, value: event.target.value }
                        : current,
                    ),
                  )
                }
              />
              <Button
                variant="link-muted"
                size="sm"
                aria-label={`Remove setup command ${index + 1}`}
                onClick={() =>
                  onChange(lines.filter((current) => current.id !== line.id))
                }
              >
                <X size={12} />
              </Button>
            </div>
            {error && (
              <Text className="pl-6 text-(--amber-11) text-[11.5px]">
                {error}
              </Text>
            )}
          </div>
        );
      })}
      <div className="flex items-center gap-3">
        <Button
          variant="outline"
          size="sm"
          disabled={disabled}
          data-attr="cost-management-image-add-setup"
          onClick={() =>
            onChange([
              ...lines,
              { id: `${idPrefix}-${lines.length}`, value: "" },
            ])
          }
        >
          <Plus size={12} />
          Add a command
        </Button>
        <Text className="text-(--gray-10) text-[11.5px]">
          One line each. Chain steps with &amp;&amp;.
        </Text>
      </div>
    </div>
  );
}
