export interface SkillStoreListEntry {
  name: string;
  description: string | null;
}

export interface SkillStoreSkill extends SkillStoreListEntry {
  body: string;
}
